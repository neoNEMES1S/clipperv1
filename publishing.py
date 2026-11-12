"""Reviewed, persistent publishing jobs. No upload runs automatically on startup."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid

from publish_accounts import Accounts, Vault, PublishError, publishing_setup, YOUTUBE_HANDLE, INSTAGRAM_HANDLE

ROOT = Path(__file__).resolve().parent
TERMINAL = {'uploaded', 'published'}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


class Store:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / 'publishing.sqlite3'
        self.path.touch(mode=0o600, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS connections (platform TEXT PRIMARY KEY, data TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS uploads '
                       '(id TEXT PRIMARY KEY, target TEXT, account TEXT, sha TEXT, record TEXT, '
                       'UNIQUE(target,account,sha))')

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def connection(self, platform: str, data) -> None:
        with self.connect() as db:
            if data is None:
                db.execute('DELETE FROM connections WHERE platform=?', (platform,))
            else:
                db.execute('INSERT OR REPLACE INTO connections VALUES (?,?)', (platform, json.dumps(data)))

    def connections(self) -> dict:
        with self.connect() as db:
            return {key: json.loads(value) for key, value in db.execute('SELECT platform,data FROM connections')}

    def get(self, identifier: str) -> dict:
        if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{32}', identifier):
            raise ValueError('Unknown upload.')
        with self.connect() as db:
            row = db.execute('SELECT record FROM uploads WHERE id=?', (identifier,)).fetchone()
        if not row:
            raise ValueError('Unknown upload.')
        return json.loads(row[0])

    def find(self, target: str, account: str, sha: str):
        with self.connect() as db:
            row = db.execute('SELECT record FROM uploads WHERE target=? AND account=? AND sha=?',
                             (target, account, sha)).fetchone()
        return json.loads(row[0]) if row else None

    def reserve(self, record: dict) -> dict:
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO uploads VALUES (?,?,?,?,?)',
                       (record['id'], record['target'], record['account'], record['sha'], json.dumps(record)))
        return self.find(record['target'], record['account'], record['sha'])

    def save(self, record: dict) -> None:
        record['updated'] = time.time()
        with self.connect() as db:
            db.execute('UPDATE uploads SET record=? WHERE id=?', (json.dumps(record), record['id']))

    def history(self) -> list[dict]:
        with self.connect() as db:
            records = [json.loads(row[0]) for row in db.execute('SELECT record FROM uploads')]
        records.sort(key=lambda record: record['updated'], reverse=True)
        fields = ('id', 'target', 'account', 'handle', 'run', 'name', 'sha', 'status', 'error', 'updated')
        return [dict({key: record[key] for key in fields},
                     progress=record['data'].get('progress', 0), url=record['data'].get('url'),
                     visibility=record['data'].get('visibility'),
                     cleanup_pending=bool(record['data'].get('object_key')),
                     account_link=bool(record['data'].get('account_link')))
                for record in records[:100]]


def posting_details(data: dict) -> tuple[list[str], dict]:
    targets = [key for key in ('youtube', 'instagram') if data.get(key) is True]
    if not targets:
        raise ValueError('Choose YouTube, Instagram, or both.')
    values = {}
    for name, limit in (('title', 100), ('description', 5000), ('caption', 2200)):
        value = data.get(name, '')
        if not isinstance(value, str) or '\x00' in value:
            raise ValueError(f'Enter valid {name} text.')
        value = value.strip()
        length = len(value.encode('utf-8')) if name == 'description' else len(value)
        if length > limit:
            raise ValueError(f'{name.capitalize()} is too long (maximum {limit}).')
        values[name] = value
    if 'youtube' in targets:
        if not values['title'] or '<' in values['title'] or '>' in values['title']:
            raise ValueError('Add a YouTube title without < or >.')
        if data.get('privacy') not in ('private', 'unlisted', 'public'):
            raise ValueError('Choose the YouTube visibility.')
        if type(data.get('made_for_kids')) is not bool:
            raise ValueError('Choose whether the YouTube video is made for kids.')
    values.update(privacy=data.get('privacy', 'private'), made_for_kids=data.get('made_for_kids'))
    return targets, values


class Publisher:
    def __init__(self, state: Path, output: Path, vault=None):
        self.store = Store(state)
        self.output = output.resolve()
        self.vault = vault or Vault(ROOT)
        self.accounts = Accounts(self.vault, self.store.connection)
        self.reviews = {}
        self.lock = threading.Lock()
        self.connection_error = ''

    def snapshot(self) -> dict:
        return {'setup_error': publishing_setup(), 'connection_error': self.connection_error,
                'connections': self.store.connections(),
                'targets': {'youtube': YOUTUBE_HANDLE, 'instagram': INSTAGRAM_HANDLE},
                'history': self.store.history()}

    def review(self, run: str, clip: dict, path: Path, data: dict) -> dict:
        from media import validate_short
        if (not re.fullmatch(r'[\w-]{1,100}', run) or run.startswith('_')
                or not re.fullmatch(r'short_\d+\.mp4', clip['name'])
                or path.resolve().parent != (self.output / run).resolve()
                or path.resolve().parent.parent != self.output):
            raise ValueError('Choose a completed clip in this workspace.')
        targets, meta = posting_details(data)
        validate_short(path, clip['end'] - clip['start'])
        if 'instagram' in targets and not 3 <= clip['end'] - clip['start'] <= 900:
            raise ValueError('Instagram Reels must be between 3 seconds and 15 minutes.')
        if path.stat().st_size > 1024 ** 3:
            raise ValueError('This publisher accepts clips up to 1 GB.')
        connections = self.store.connections()
        for target in targets:
            if target not in connections:
                raise ValueError(f'Connect {target.capitalize()} first.')
        if 'instagram' in targets and 'storage' not in connections:
            raise ValueError('Configure temporary media storage for Instagram first.')
        digest = file_hash(path)
        entries = []
        for target in targets:
            account = connections[target]
            old = self.store.find(target, account['id'], digest)
            if old and old['status'] not in TERMINAL and old['meta'] != meta:
                raise ValueError('This clip has an unfinished upload with different details. Use Resume in upload history.')
            entries.append({'target': target, 'account': account['id'], 'handle': account['handle'],
                            'previous': old['id'] if old else None,
                            'status': old['status'] if old else 'ready',
                            'url': old['data'].get('url') if old else None})
        plan = {'run': run, 'name': clip['name'], 'path': str(path.resolve()),
                'duration': clip['end'] - clip['start'], 'sha': digest, 'meta': meta, 'entries': entries,
                'storage': connections.get('storage', {}).get('id'), 'created': time.time(), 'retry': False}
        return self.save_review(plan, clip['url'] + '?v=' + digest[:16])

    def review_retry(self, identifier: str) -> dict:
        record = self.store.get(identifier)
        connections = self.store.connections()
        account = connections.get(record['target'], {})
        if account.get('id') != record['account']:
            raise ValueError('Reconnect the original destination account before resuming.')
        if record['status'] in TERMINAL and not record['data'].get('object_key'):
            raise ValueError('This clip has already been uploaded.')
        plan = {'run': record['run'], 'name': record['name'], 'path': record['asset'],
                'duration': record['duration'], 'sha': record['sha'], 'meta': record['meta'],
                'entries': [{'target': record['target'], 'account': record['account'], 'handle': record['handle'],
                             'previous': record['id'], 'status': record['status'], 'url': record['data'].get('url')}],
                'storage': record.get('storage'), 'created': time.time(), 'retry': True}
        return self.save_review(plan, '/publish-media/' + identifier)

    def save_review(self, plan: dict, preview: str) -> dict:
        key = secrets.token_urlsafe(32)
        with self.lock:
            self.reviews = {k: v for k, v in self.reviews.items() if time.time() - v['created'] <= 600}
            if len(self.reviews) >= 20:
                raise ValueError('Close old reviews and try again shortly.')
            self.reviews[key] = plan
        return {'review_id': key, 'run': plan['run'], 'name': plan['name'], 'sha': plan['sha'][:12],
                'duration': plan['duration'], 'meta': plan['meta'], 'destinations': plan['entries'],
                'preview': preview, 'retry': plan['retry']}

    def asset_for(self, identifier: str) -> Path:
        record = self.store.get(identifier)
        path = Path(record['asset']).resolve()
        root = (self.store.directory / 'publish_media').resolve()
        if path.parent != root or path.name != record['sha'] + '.mp4' or not path.is_file():
            raise FileNotFoundError('The saved upload clip is missing.')
        return path

    def commit(self, key: str) -> tuple[list[str], str]:
        with self.lock:
            plan = self.reviews.pop(key, None)
        if not plan or time.time() - plan['created'] > 600:
            raise ValueError('This review expired. Review the upload again.')
        connections = self.store.connections()
        for entry in plan['entries']:
            if connections.get(entry['target'], {}).get('id') != entry['account']:
                raise ValueError('The connected account changed. Review the upload again.')
        if any(e['target'] == 'instagram' for e in plan['entries']):
            if connections.get('storage', {}).get('id') != plan['storage']:
                raise ValueError('Temporary storage changed. Restore it or review the upload again.')
        path = Path(plan['path'])
        if not path.is_file() or file_hash(path) != plan['sha']:
            raise ValueError('The clip changed or is missing. Review its current version before uploading.')
        assets = self.store.directory / 'publish_media'
        assets.mkdir(exist_ok=True, mode=0o700)
        asset = assets / (plan['sha'] + '.mp4')
        if not asset.exists():
            temporary_path = None
            try:
                with tempfile.NamedTemporaryFile(dir=assets, delete=False) as temporary:
                    temporary_path = Path(temporary.name)
                    with path.open('rb') as stream:
                        shutil.copyfileobj(stream, temporary, 1024 * 1024)
                    temporary.flush()
                if file_hash(temporary_path) != plan['sha']:
                    raise ValueError('The clip changed during review. Review it again.')
                temporary_path.replace(asset)
            finally:
                if temporary_path:
                    temporary_path.unlink(missing_ok=True)
        if file_hash(asset) != plan['sha']:
            raise ValueError('The saved upload clip is damaged. Restore it before resuming.')
        # Frozen reviewed bytes make retries independent of later headline edits.
        identifiers = []
        for entry in plan['entries']:
            record = self.store.get(entry['previous']) if entry['previous'] else self.store.reserve({
                'id': uuid.uuid4().hex, 'target': entry['target'], 'account': entry['account'],
                'handle': entry['handle'], 'run': plan['run'], 'name': plan['name'], 'sha': plan['sha'],
                'duration': plan['duration'], 'asset': str(asset), 'meta': plan['meta'],
                'storage': plan['storage'], 'status': 'queued', 'data': {}, 'error': '', 'updated': time.time()})
            if record['status'] not in TERMINAL and record['meta'] != plan['meta']:
                raise ValueError('A saved upload has different details. Resume it from history.')
            if record['status'] not in TERMINAL or record['data'].get('object_key'):
                identifiers.append(record['id'])
        if not identifiers:
            raise ValueError('These destinations already have this clip. Open the saved post links in history.')
        return identifiers, plan['run']

    def run(self, identifiers: list[str]) -> bool:
        from publish_uploads import youtube_upload, instagram_upload, cleanup_staging
        failed = False
        for identifier in identifiers:
            record = self.store.get(identifier)
            if record['status'] in TERMINAL and not record['data'].get('object_key'):
                continue
            if file_hash(self.asset_for(identifier)) != record['sha']:
                raise PublishError('The reviewed upload asset is damaged. No upload was attempted.')

            def save(stage: str):
                self.store.save(record)
                print(f'upload: {record["target"]}: {stage}', flush=True)

            try:
                record.update(status='uploading', error='')
                save('starting saved attempt')
                if record['target'] == 'youtube':
                    youtube_upload(self, record, save)
                elif record['data'].get('remote_id') or record['data'].get('published'):
                    record['status'] = 'published'
                    cleanup_staging(self, record, save)
                else:
                    instagram_upload(self, record, save)
            except (Exception, KeyboardInterrupt) as exc:
                failed = True
                if record['status'] not in TERMINAL:
                    record['status'] = 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed'
                record['error'] = (str(exc) if isinstance(exc, PublishError)
                                   else 'Upload interrupted. Resume the saved attempt; do not create a duplicate upload.')
                save(record['error'])
                if isinstance(exc, KeyboardInterrupt):
                    break
            else:
                save('complete')
        return not failed


def main() -> None:
    parser = argparse.ArgumentParser(description='Run previously reviewed publishing jobs')
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run', required=True)
    parser.add_argument('--jobs', nargs='+', required=True)
    args = parser.parse_args()
    try:
        publisher = Publisher(args.state, args.output)
        # Separate dashboard instances must not send the same saved upload concurrently.
        with (publisher.store.directory / 'publish.lock').open('a+b') as lock:
            if os.name == 'nt':
                import msvcrt
                lock.write(b'0')
                lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            success = publisher.run(args.jobs)
        print(f'done: {args.output.resolve() / args.run / "manifest.json"}', flush=True)
        if not success:
            raise SystemExit(1)
    except (PublishError, ValueError, OSError) as exc:
        parser.exit(1, f'Publishing stopped: {exc}\n')


if __name__ == '__main__':
    main()
