"""Local browser interface for the existing clipper CLI; no web dependencies."""
from __future__ import annotations

import argparse
from collections import deque
from functools import lru_cache
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit
import webbrowser

from youtube_source import replay_filename, replay_source_path, youtube_video_id
from clip_titles import reel_caption, youtube_description
from publishing import Publisher
from publish_accounts import PublishError, publishing_setup
from story_clips import reviewed_stories

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / 'web'
POSTER_WORKERS = threading.BoundedSemaphore(2)


def pipeline_environment() -> dict[str, str]:
    env = os.environ.copy()
    env['PATH'] = os.pathsep.join([str(ROOT / '.local' / 'bin'), str(Path(sys.executable).parent),
                                  '/opt/homebrew/bin', '/usr/local/bin', env.get('PATH', '')])
    env['PYTHONUNBUFFERED'] = '1'
    return env


@lru_cache(maxsize=128)
def clip_poster(file: Path, version: tuple[int, int, int], timestamp: float) -> bytes:
    result = subprocess.run(
        ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-ss', str(timestamp),
         '-i', str(file), '-map', '0:v:0', '-frames:v', '1', '-vf', 'scale=360:-2',
         '-c:v', 'mjpeg', '-f', 'image2pipe', 'pipe:1'],
        env=pipeline_environment(), capture_output=True, timeout=20)
    if result.returncode or not result.stdout.startswith(b'\xff\xd8'):
        raise ValueError('A thumbnail frame could not be decoded.')
    return result.stdout


class Workspace:
    def __init__(self, output: Path):
        self.output = output.resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        state = ROOT / '.local' if self.output == (ROOT / 'shorts').resolve() else self.output.parent / '.local'
        self.publisher = Publisher(state, self.output)
        self.job = {'status': 'idle', 'url': '', 'max_clips': 25, 'result_run': None}
        self.lines: deque[str] = deque(maxlen=150)
        self.process: subprocess.Popen | None = None
        self.env = pipeline_environment()
        self.missing = [name for name in ('ffmpeg', 'ffprobe')
                        if not shutil.which(name, path=self.env['PATH'])]
        self.missing += [name for name in ('numpy', 'faster_whisper')
                         if importlib.util.find_spec(name) is None]
        self.combat_missing = ([] if importlib.util.find_spec('rapidocr_onnxruntime')
                               else ['rapidocr_onnxruntime'])

    def run_directory(self, identity: str) -> Path:
        if not re.fullmatch(r'[\w-]{1,100}', identity) or identity.startswith('_'):
            raise FileNotFoundError('Run not found.')
        path = (self.output / identity).resolve()
        if path.parent != self.output or not path.is_dir():
            raise FileNotFoundError('Run not found.')
        return path

    def read_run(self, identity: str) -> dict:
        directory = self.run_directory(identity)
        manifest = directory / 'manifest.json'
        if manifest.resolve().parent != directory:
            raise FileNotFoundError('Run not found.')
        data = json.loads(manifest.read_text(encoding='utf-8'))
        game = data.get('config', {}).get('game', 'fortnite')
        clips = []
        for clip in data.get('shorts', []):
            name = clip.get('path', '')
            if (clip.get('status') != 'review_required' or not isinstance(name, str)
                    or not re.fullmatch(r'short_\d+\.mp4', name)):
                continue
            file = (directory / name).resolve()
            if file.parent != directory or not file.is_file() or file.stat().st_size == 0:
                continue
            start, end = float(clip['start_seconds']), float(clip['end_seconds'])
            if not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end:
                continue
            headline = clip.get('headline', str(clip.get('title', '')).removesuffix(' #Fortnite #Shorts').removesuffix(' #GTA6 #Shorts'))
            caption = clip.get('reel_caption') or reel_caption(
                game, clip.get('transcript') or '', headline or 'Gameplay highlight')
            clips.append({'name': name, 'start': start, 'end': end,
                          'title': str(clip.get('title', 'Draft clip')),
                          'description': youtube_description(str(clip.get('description') or ''), caption),
                          'headline': headline,
                          'reel_caption': caption,
                          'captions': bool(clip.get('captions')),
                          'poster': f'/poster/{identity}/{name}',
                          'url': f'/media/{identity}/{name}'})
        source = data.get('source', {})
        source_url = source.get('url') or data.get('source_url')
        source_id = source.get('video_id')
        if not source_id and source_url:
            try:
                source_id = youtube_video_id(source_url)
            except ValueError:
                pass
        stat = directory.stat()
        source_path = Path(source.get('path') or identity)
        replay = replay_filename(replay_source_path(source_path, self.output / '_youtube_downloads')) if source_id else None
        waiting = data.get('status') == 'awaiting_story_review'
        return {'id': identity, 'revision': str(manifest.stat().st_mtime_ns),
                'source_id': source_id or identity,
                'source_label': source.get('title') or (replay['title'] if replay else None) or source_id or source_path.name,
                'batch_date': getattr(stat, 'st_birthtime', stat.st_mtime),
                'source_url': source_url, 'status': data.get('status', 'unknown'),
                'game': game,
                'story_mode': 'story_brief' in data.get('config', {}),
                'stories': data.get('candidates', []) if waiting else [],
                'duration': data.get('duration_seconds') if waiting else None,
                'combat_only': bool(data.get('config', {}).get('combat_only')),
                'clips': clips, 'warnings': data.get('warnings', []), 'error': data.get('error')}

    def runs(self) -> list[dict]:
        runs = []
        for directory in self.output.iterdir():
            try:
                runs.append(self.read_run(directory.name))
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                continue  # A writer may be replacing a manifest; retry on the next poll.
        return sorted(runs, key=lambda run: run['revision'], reverse=True)

    def downloads(self) -> list[dict]:
        cache = self.output / '_youtube_downloads'
        if cache.is_symlink() or not cache.is_dir():
            return []
        items = []
        for path in cache.iterdir():
            replay = replay_filename(path)
            if not replay or path.is_symlink() or not path.is_file():
                continue
            try:
                info = path.stat()
            except FileNotFoundError:
                continue
            items.append({'name': path.name, 'source_id': replay['id'], 'title': replay['title'], 'bytes': info.st_size,
                          'modified': info.st_mtime})
        return sorted(items, key=lambda item: (item['modified'], item['name']))

    def delete_download(self, name, modified) -> None:
        with self.lock:
            if self.job['status'] == 'running':
                raise ValueError('Wait for the current job to finish before removing a download.')
            if not any(item['name'] == name and item['modified'] == modified for item in self.downloads()):
                raise ValueError('This download changed or is no longer available. Refresh and try again.')
            (self.output / '_youtube_downloads' / name).unlink()

    def snapshot(self) -> dict:
        with self.lock:
            job = dict(self.job, log=list(self.lines))
        return {'app': 'clipper-local', 'token': self.token, 'job': job,
                'runs': self.runs(), 'missing': self.missing, 'combat_missing': self.combat_missing,
                'downloads': self.downloads(), 'publishing': self.publisher.snapshot()}

    def publishing_action(self, action: str, data: dict, callback: str) -> dict:
        with self.lock:
            if self.job['status'] == 'running':
                raise RuntimeError('Wait for the current job to finish before changing publishing settings or uploading.')
            if publishing_setup():
                raise ValueError(publishing_setup())
            accounts = self.publisher.accounts
            if action == 'youtube-config':
                accounts.configure_google(data.get('config'))
            elif action == 'youtube-connect':
                self.publisher.connection_error = ''
                return {'url': accounts.google_begin(callback)}
            elif action == 'instagram-connect':
                accounts.instagram_connect(data.get('access_token'), data.get('app_secret', ''),
                                           data.get('login_mode', 'instagram'))
            elif action == 'storage-connect':
                accounts.storage_connect(data)
            elif action == 'disconnect':
                accounts.disconnect(data.get('platform'))
            elif action == 'prepare':
                run = self.read_run(data.get('run', ''))
                clip = next((c for c in run['clips'] if c['name'] == data.get('clip')), None)
                if not clip:
                    raise ValueError('Choose a completed clip.')
                return self.publisher.review(run['id'], clip, self.run_directory(run['id']) / clip['name'], data)
            elif action == 'prepare-batch':
                run = self.read_run(data.get('run', ''))
                if data.get('revision') != str(run['revision']):
                    raise ValueError('This run changed. Review the refreshed clips.')
                names = data.get('clips')
                if not isinstance(names, list) or not names or any(not isinstance(name, str) for name in names):
                    raise ValueError('Select at least one clip.')
                clips = [clip for clip in run['clips'] if clip['name'] in names]
                if len(clips) != len(names):
                    raise ValueError('Choose clips from the current run.')
                return self.publisher.review_batch(run['id'], clips, self.run_directory(run['id']), data)
            elif action == 'retry-review':
                return self.publisher.review_retry(data.get('id'))
            elif action == 'retry-reels':
                return self.publisher.review_failed_reels()
            elif action == 'commit':
                ids, run = self.publisher.commit(data.get('review_id'))
                command = [sys.executable, '-u', str(ROOT / 'publishing.py'), '--state',
                           str(self.publisher.store.directory), '--output', str(self.output), '--run', run,
                           '--jobs', *ids]
                self.launch(command, url='', maximum=0, kind='publish')
                return {'status': 'running'}
            else:
                raise ValueError('Unknown publishing action.')
            return {'status': 'saved'}

    def start(self, url: str, maximum: int, game: str = 'fortnite', new_moments: bool = False,
              mode: str = 'replay', story_brief: str = '') -> None:
        if not isinstance(url, str) or len(url) > 2048:
            raise ValueError('Paste a completed YouTube replay URL.')
        if mode not in ('replay', 'live'):
            raise ValueError('Choose Replay or Live stream.')
        identity = youtube_video_id(url.strip())
        if type(maximum) is not int or not 1 <= maximum <= 100:
            raise ValueError('Choose a clip limit between 1 and 100.')
        if game not in ('fortnite', 'gta6'):
            raise ValueError('Choose Fortnite or GTA 6.')
        if not isinstance(story_brief, str) or len(story_brief) > 500 or '\x00' in story_brief:
            raise ValueError('Keep the stream brief within 500 plain-text characters.')
        missing = self.missing + (self.combat_missing if game == 'fortnite' else [])
        if missing:
            raise ValueError('Setup needed: missing ' + ', '.join(missing) + '. See README setup instructions.')
        canonical = f'https://www.youtube.com/watch?v={identity}'
        model = 'models/small' if (ROOT / 'models' / 'small' / 'model.bin').is_file() else 'small'
        command = [sys.executable, '-u', str(ROOT / 'clipper.py'), '--input', canonical,
                   '--output', str(self.output), '--max-shorts', str(maximum), '--model', model,
                   '--game', game, '--auto-title', '--pre-roll', '28', '--post-roll', '8']
        command.append('--live' if mode == 'live' else '--audience-peaks')
        if new_moments is True:
            command.append('--new-moments')
        if game == 'fortnite':
            command.append('--combat-only')
        else:
            command.append('--story-brief=' + story_brief.strip())
        self.launch(command, url=canonical, maximum=maximum, kind=mode, game=game)

    def start_story_render(self, identity: str, revision: str, cuts: list) -> None:
        run = self.read_run(identity)
        if run['status'] != 'awaiting_story_review' or revision != run['revision']:
            raise ValueError('The story review changed. Refresh and review this batch again.')
        manifest = self.run_directory(identity) / 'manifest.json'
        report = json.loads(manifest.read_text(encoding='utf-8'))
        reviewed_stories(run['stories'], cuts, run['duration'], report['config'].get('excluded_windows', []))
        command = [sys.executable, '-u', str(ROOT / 'clipper.py'), '--output', str(self.output),
                   '--story-render', str(manifest), '--story-cuts', json.dumps(cuts, allow_nan=False)]
        self.launch(command, url=run['source_url'], maximum=len(cuts), kind='story-render', game='gta6')

    def cancel_live(self) -> None:
        with self.lock:
            if self.job['status'] != 'running' or self.job.get('kind') != 'live':
                raise ValueError('There is no live job to stop.')
            self.job['cancelled'] = True
            self.close()

    def start_headline(self, run: str, name: str, text: str) -> None:
        from edit_clip import normalize_headline
        text = normalize_headline(text)
        report = self.read_run(run)
        if not any(c['name'] == name for c in report['clips']):
            raise FileNotFoundError('Choose a completed clip.')
        command = [sys.executable, '-u', str(ROOT / 'edit_clip.py'), '--output', str(self.output),
                   '--run', run, '--clip', name, '--headline=' + text]
        self.launch(command, url=report['source_url'], maximum=len(report['clips']), kind='headline')

    def launch(self, command: list[str], *, url: str, maximum: int, kind: str,
               game: str | None = None) -> None:
        with self.lock:
            if self.job['status'] == 'running':
                raise RuntimeError('A job is already processing. Wait for it to finish.')
            options = ({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt'
                       else {'start_new_session': True})
            self.process = subprocess.Popen(command, cwd=ROOT, env=self.env, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                            errors='replace', bufsize=1, **options)
            self.job = {'status': 'running', 'url': url, 'max_clips': maximum, 'result_run': None,
                        'kind': kind, 'game': game}
            self.lines.clear()
            self.lines.append('Starting reviewed upload…' if kind == 'publish' else
                              'Starting headline render…' if kind == 'headline' else
                              f'Starting {"GTA 6" if game == "gta6" else "Fortnite"} replay processing…')
            threading.Thread(target=self.collect, args=(self.process,), daemon=True).start()

    def collect(self, process: subprocess.Popen) -> None:
        try:
            for line in process.stdout:
                line = line.strip()[-3000:]
                if not line:
                    continue
                with self.lock:
                    self.lines.append(line)
                    if line.startswith('done: '):
                        manifest = Path(line[6:]).resolve()
                        if manifest.name == 'manifest.json' and manifest.parent.parent == self.output:
                            self.job['result_run'] = manifest.parent.name
            code = process.wait()
            with self.lock:
                if self.job.get('cancelled'):
                    self.job['status'] = 'cancelled'
                    self.lines.append('Live job stopped.')
                else:
                    self.job['status'] = 'complete' if code == 0 else 'failed'
                if code and not self.job.get('cancelled'):
                    self.lines.append('Processing stopped. Check the error above, then retry; source downloads are retained.')
        except OSError as exc:
            with self.lock:
                self.job['status'] = 'failed'
                self.lines.append(f'Could not read processing progress: {exc}')
        finally:
            process.stdout.close()

    def close(self) -> None:
        with self.lock:
            process = self.process
        if process is not None and process.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
            else:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def open_folder(directory: Path) -> None:
    if sys.platform == 'win32':
        os.startfile(str(directory))
    else:
        subprocess.run(['open' if sys.platform == 'darwin' else 'xdg-open', str(directory)],
                       check=True, capture_output=True)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_args) -> None:
        pass

    @property
    def workspace(self) -> Workspace:
        return self.server.workspace

    def local_request(self) -> bool:
        host = self.headers.get('Host', '')
        expected = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if host not in expected or self.headers.get('Origin', 'http://' + host) != 'http://' + host:
            self.json_response({'error': 'Only this local workspace may access the server.'}, 403)
            return False
        return True

    def response_headers(self, status: int, kind: str, length: int, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "media-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def json_response(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.response_headers(status, 'application/json; charset=utf-8', len(body))
        if self.command != 'HEAD':
            self.wfile.write(body)

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        if not self.local_request():
            return
        target = urlsplit(self.path)
        path = unquote(target.path)
        try:
            if path == '/api/state':
                self.json_response(self.workspace.snapshot())
            elif path == '/oauth/youtube/callback':
                values = parse_qs(target.query)
                try:
                    self.workspace.publisher.accounts.google_finish(values.get('state', [''])[0],
                                                                     values.get('code', [''])[0])
                    self.workspace.publisher.connection_error = ''
                except (PublishError, ValueError) as exc:
                    self.workspace.publisher.connection_error = str(exc)
                self.response_headers(303, 'text/plain', 0, {'Location': '/#publishing'})
            elif path in ('/', '/app.css', '/app.js'):
                name, kind = {'/': ('index.html', 'text/html; charset=utf-8'),
                              '/app.css': ('app.css', 'text/css; charset=utf-8'),
                              '/app.js': ('app.js', 'text/javascript; charset=utf-8')}[path]
                body = (ASSETS / name).read_bytes()
                self.response_headers(200, kind, len(body))
                if self.command != 'HEAD':
                    self.wfile.write(body)
            elif path.startswith(('/media/', '/poster/')):
                parts = path.split('/')
                if len(parts) != 4:
                    raise FileNotFoundError('Clip not found.')
                run = self.workspace.read_run(parts[2])
                clip = next((c for c in run['clips'] if c['name'] == parts[3]), None)
                if clip is None:
                    raise FileNotFoundError('Clip not found.')
                directory = self.workspace.run_directory(parts[2])
                file = (directory / parts[3]).resolve()
                if file.parent != directory:
                    raise FileNotFoundError('Clip not found.')
                if parts[1] == 'poster':
                    stat = file.stat()
                    version = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
                    timestamp = round(min(3, (clip['end'] - clip['start']) * .15), 3)
                    with POSTER_WORKERS:
                        body = clip_poster(file, version, timestamp)
                    self.response_headers(200, 'image/jpeg', len(body))
                    if self.command != 'HEAD':
                        self.wfile.write(body)
                else:
                    self.media(file, parse_qs(target.query).get('download') == ['1'])
            elif path.startswith('/publish-media/'):
                self.media(self.workspace.publisher.asset_for(path.removeprefix('/publish-media/')), False)
            elif path == '/favicon.ico':
                self.response_headers(204, 'image/x-icon', 0)
            else:
                raise FileNotFoundError('Page not found.')
        except (FileNotFoundError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
            self.json_response({'error': 'File not found.'}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def media(self, file: Path, download: bool) -> None:
        with file.open('rb') as stream:
            size = os.fstat(stream.fileno()).st_size
            start, end, status = 0, size - 1, 200
            extra = {'Accept-Ranges': 'bytes'}
            requested = self.headers.get('Range')
            if requested:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
                if match and any(match.groups()):
                    a, b = match.groups()
                    start = int(a) if a else max(0, size - int(b))
                    end = min(size - 1, int(b)) if a and b else size - 1
                else:
                    start, end = size, -1
                if start >= size or start > end:
                    self.response_headers(416, 'video/mp4', 0, {'Content-Range': f'bytes */{size}'})
                    return
                status = 206
                extra['Content-Range'] = f'bytes {start}-{end}/{size}'
            if download:
                extra['Content-Disposition'] = f'attachment; filename="{file.name}"'
            self.response_headers(status, 'video/mp4', end - start + 1, extra)
            if self.command == 'HEAD':
                return
            stream.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                block = stream.read(min(65536, remaining))
                if not block:
                    break
                self.wfile.write(block)
                remaining -= len(block)

    def do_POST(self) -> None:
        if not self.local_request():
            return
        if not secrets.compare_digest(self.headers.get('X-Clipper-Token', ''), self.workspace.token):
            self.json_response({'error': 'Refresh this page before trying again.'}, 403)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 65536 or self.headers.get_content_type() != 'application/json':
                raise ValueError('Expected a small JSON request.')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Expected an object.')
            if self.path == '/api/start':
                self.workspace.start(data.get('url'), data.get('max_clips'), data.get('game', 'fortnite'),
                                     data.get('new_moments', False), data.get('mode', 'replay'),
                                     data.get('story_brief', ''))
                self.json_response({'status': 'running'}, 202)
            elif self.path == '/api/story-render':
                self.workspace.start_story_render(data.get('run', ''), data.get('revision'), data.get('cuts'))
                self.json_response({'status': 'running'}, 202)
            elif self.path == '/api/live/stop':
                self.workspace.cancel_live()
                self.json_response({'status': 'stopping'})
            elif self.path == '/api/headline':
                self.workspace.start_headline(data.get('run', ''), data.get('clip', ''), data.get('headline'))
                self.json_response({'status': 'running'}, 202)
            elif self.path == '/api/downloads/remove':
                self.workspace.delete_download(data.get('name'), data.get('modified'))
                self.json_response({'status': 'removed'})
            elif self.path == '/api/open-folder':
                open_folder(self.workspace.run_directory(data.get('run', '')))
                self.json_response({'status': 'opened'})
            elif self.path.startswith('/api/publish/'):
                callback = f'http://127.0.0.1:{self.server.server_port}/oauth/youtube/callback'
                result = self.workspace.publishing_action(self.path.removeprefix('/api/publish/'), data, callback)
                self.json_response(result)
            else:
                self.json_response({'error': 'Action not found.'}, 404)
        except (ValueError, TypeError) as exc:
            self.json_response({'error': str(exc)}, 400)
        except FileNotFoundError:
            self.json_response({'error': 'Output folder not found.'}, 404)
        except RuntimeError as exc:
            self.json_response({'error': str(exc)}, 409)
        except (OSError, subprocess.SubprocessError) as exc:
            self.json_response({'error': f'Could not complete the action: {exc}'}, 500)


def main() -> None:
    parser = argparse.ArgumentParser(description='Open the local Clipper dashboard')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    os.environ['PATH'] = pipeline_environment()['PATH']
    workspace = Workspace(ROOT / 'shorts')
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    except OSError:
        parser.exit(1, f'Cannot open port {args.port}. Close the other Clipper window or use --port with another port.\n')
    server.workspace = workspace
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Clipper is ready: {url}\nKeep this window open while processing. Press Ctrl+C to stop.', flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopping Clipper; downloads and completed clips are retained.')
    finally:
        server.server_close()
        workspace.close()


if __name__ == '__main__':
    main()
