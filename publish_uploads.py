"""Platform protocols; all calls are made only for an explicitly reviewed job."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

from publish_accounts import GRAPH, PublishError, api_json, google_session, instagram_session

CHUNK = 8 * 1024 * 1024


def google_upload_url(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname
            or not (parsed.hostname == 'googleapis.com' or parsed.hostname.endswith('.googleapis.com'))
            or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.fragment):
        raise PublishError('YouTube returned an unexpected upload destination. Upload stopped.')
    return value


def youtube_upload(publisher, record: dict, save) -> None:
    session, account = google_session(publisher.vault)
    if account['id'] != record['account']:
        raise PublishError('The connected YouTube channel changed. Reconnect the original channel.')
    size = Path(record['asset']).stat().st_size
    key = 'upload:' + record['id']
    saved_session = publisher.vault.get(key)
    meta = record['meta']
    if not saved_session:
        try:
            response = session.request('POST', 'https://www.googleapis.com/upload/youtube/v3/videos',
                                       params={'uploadType': 'resumable', 'part': 'snippet,status'},
                                       json={'snippet': {'title': meta['title'], 'description': meta['description'],
                                                         'categoryId': '20'},
                                             'status': {'privacyStatus': meta['privacy'],
                                                        'selfDeclaredMadeForKids': meta['made_for_kids']}},
                                       headers={'X-Upload-Content-Length': str(size),
                                                'X-Upload-Content-Type': 'video/mp4'},
                                       timeout=45, allow_redirects=False)
        except Exception:
            raise PublishError('Could not start the YouTube upload. No video bytes were sent; retry this attempt.') from None
        if response.status_code not in (200, 201):
            raise PublishError(f'YouTube rejected upload setup (HTTP {response.status_code}). Check permissions and posting details.')
        uri = google_upload_url(response.headers.get('Location', ''))
        publisher.vault.put(key, {'uri': uri})
    else:
        uri = google_upload_url(saved_session['uri'])

    def probe_offset():
        try:
            return session.request('PUT', uri, data=b'',
                                   headers={'Content-Length': '0', 'Content-Range': f'bytes */{size}'},
                                   timeout=60, allow_redirects=False)
        except Exception:
            raise PublishError('YouTube upload status could not be checked. Resume this saved attempt later.') from None

    response = probe_offset()
    failures = 0
    last_offset = -1
    with Path(record['asset']).open('rb') as stream:
        while response.status_code == 308:
            acknowledged = response.headers.get('Range', '')
            match = re.fullmatch(r'bytes=0-(\d+)', acknowledged) if acknowledged else None
            if acknowledged and not match:
                raise PublishError('YouTube returned an invalid byte range. Resume after checking the upload.')
            offset = int(match[1]) + 1 if match else 0
            failures = failures + 1 if offset <= last_offset else 0
            last_offset = offset
            if failures > 3:
                raise PublishError('YouTube is not acknowledging new bytes. Resume this saved upload later.')
            if not 0 <= offset < size:
                raise PublishError('YouTube has all bytes but has not confirmed the video. Resume later to check it.')
            record['data']['progress'] = round(offset * 100 / size)
            save(f'{record["data"]["progress"]}% transferred')
            stream.seek(offset)
            block = stream.read(min(CHUNK, size - offset))
            if not block:
                raise PublishError('The reviewed video file is incomplete. Upload stopped.')
            try:
                response = session.request('PUT', uri, data=block,
                                           headers={'Content-Type': 'video/mp4',
                                                    'Content-Length': str(len(block)),
                                                    'Content-Range': f'bytes {offset}-{offset+len(block)-1}/{size}'},
                                           timeout=90, allow_redirects=False)
            except Exception:
                failures += 1
                if failures > 3:
                    raise PublishError('YouTube transfer interrupted. Resume this saved upload to continue.') from None
                response = probe_offset()
                continue
            if response.status_code in (429, 500, 502, 503, 504):
                failures += 1
                if failures > 3:
                    raise PublishError('YouTube is temporarily unavailable. Resume this upload later.')
                time.sleep(min(2 ** failures, 8))
                response = probe_offset()
    if response.status_code not in (200, 201):
        if response.status_code in (404, 410):
            raise PublishError('The YouTube session expired. Check YouTube Studio before starting another upload; '
                               'Clipper will not create a possible duplicate automatically.')
        raise PublishError(f'YouTube did not confirm completion (HTTP {response.status_code}). Resume to check this session.')
    try:
        result = response.json()
        identity = result['id']
        if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', identity):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise PublishError('YouTube completion was received without a usable video ID. Check Studio before retrying.') from None
    record['status'] = 'uploaded'
    record['data'].update(remote_id=identity, url='https://youtu.be/' + identity, progress=100,
                          visibility=result.get('status', {}).get('privacyStatus', 'unknown'))
    save('video uploaded; YouTube may still be processing it')
    account['credentials'] = json.loads(session.credentials.to_json())
    publisher.vault.put('youtube', account)
    # Retain the encrypted session receipt for reconciliation if local state recovery is needed.


def storage_client(config: dict):
    import boto3
    from botocore.config import Config
    return boto3.client('s3', endpoint_url=config['endpoint'], region_name=config['region'],
                        aws_access_key_id=config['access_key'], aws_secret_access_key=config['secret_key'],
                        config=Config(signature_version='s3v4', s3={'addressing_style': 'path'},
                                      connect_timeout=20, read_timeout=60, retries={'max_attempts': 3}))


def storage_for(publisher, record):
    config = publisher.vault.get('storage')
    if not config or config['id'] != record['storage']:
        raise PublishError('Reconnect the same temporary storage bucket used for this upload.')
    return storage_client(config), config


def object_prefix(publisher) -> str:
    return 'clipper/' + hashlib.sha256(str(publisher.store.directory).encode()).hexdigest()[:16] + '/'


def cleanup_staging(publisher, record: dict, save) -> None:
    key = record['data'].get('object_key')
    if not key:
        return
    if key != object_prefix(publisher) + record['id'] + '.mp4':
        raise PublishError('Unexpected temporary object key. Cleanup stopped.')
    client, config = storage_for(publisher, record)
    try:
        client.delete_object(Bucket=config['bucket'], Key=key)
    except Exception:
        raise PublishError('Temporary video cleanup failed. Retry the saved action from upload history.') from None
    record['data'].pop('object_key', None)
    save('temporary storage copy removed')


def instagram_asset(publisher, record: dict) -> Path:
    from media import run, validate_short
    target = publisher.store.directory / 'publish_media' / (record['sha'] + '.instagram.mp4')
    if target.is_file():
        validate_short(target, record['duration'])
        return target
    partial = target.with_suffix('.partial.mp4')
    try:
        run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', record['asset'],
             '-map', '0:v:0', '-map', '0:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k',
             '-ar', '48000', '-ac', '2', '-movflags', '+faststart', str(partial)])
        validate_short(partial, record['duration'])
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def media_id(result: dict) -> str:
    identity = str(result.get('id', ''))
    if not re.fullmatch(r'\d{1,64}', identity):
        raise PublishError('Instagram returned an unexpected media ID. Check the account before retrying.')
    return identity


def mark_instagram_published(publisher, session, record, result, save):
    data = record['data']
    identity = media_id(result) if result else None
    record['status'] = 'published'
    data.update(published=True, progress=100)
    if result:
        data['remote_id'] = identity
    # PUBLISHED container status can confirm a timed-out publish without returning its post ID.
    data.update(url='https://www.instagram.com/' + record['handle'] + '/', account_link=True)
    save('Reel published')
    if data.get('remote_id'):
        try:
            link = api_json(session, 'GET', GRAPH + '/' + data['remote_id'], 'Instagram',
                            params={'fields': 'permalink'}).get('permalink', '')
            parsed = urlsplit(link)
            if parsed.scheme == 'https' and parsed.hostname in ('www.instagram.com', 'instagram.com'):
                data.update(url=link, account_link=False)
                save('post link saved')
        except PublishError:
            pass  # Publication is already confirmed; never turn a missing permalink into a new upload.
    cleanup_staging(publisher, record, save)


def instagram_upload(publisher, record: dict, save) -> None:
    session, account = instagram_session(publisher.vault, publisher.store.connection)
    if account['id'] != record['account']:
        raise PublishError('The connected Instagram account changed. Reconnect the original account.')
    data = record['data']
    existing = data.get('container')
    if existing:
        if not re.fullmatch(r'\d{1,64}', existing):
            raise PublishError('Invalid saved Instagram container.')
        status = api_json(session, 'GET', GRAPH + '/' + existing, 'Instagram',
                          params={'fields': 'status_code'}).get('status_code')
        if status == 'PUBLISHED':
            mark_instagram_published(publisher, session, record, None, save)
            return
        if status in ('ERROR', 'EXPIRED'):
            if data.get('publish_requested'):
                raise PublishError('Instagram could not confirm the earlier publish. Check the account before creating another post.')
            cleanup_staging(publisher, record, save)
            data.pop('container', None)
    if not data.get('container'):
        asset = instagram_asset(publisher, record)
        client, config = storage_for(publisher, record)
        key = object_prefix(publisher) + record['id'] + '.mp4'
        data['object_key'] = key
        save('staging only the selected clip')
        try:
            from boto3.s3.transfer import TransferConfig
            client.upload_file(str(asset), config['bucket'], key,
                               ExtraArgs={'ContentType': 'video/mp4'},
                               Config=TransferConfig(multipart_threshold=64*1024*1024, max_concurrency=1,
                                                     use_threads=False))
            url = client.generate_presigned_url('get_object', Params={'Bucket': config['bucket'], 'Key': key},
                                                ExpiresIn=3600)
        except Exception:
            raise PublishError('Temporary storage upload failed. Check the bucket permissions and resume this attempt.') from None
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname != urlsplit(config['endpoint']).hostname:
            raise PublishError('Storage returned an unexpected media URL. Upload stopped.')
        result = api_json(session, 'POST', GRAPH + '/' + record['account'] + '/media', 'Instagram',
                          json={'media_type': 'REELS', 'video_url': url, 'caption': record['meta']['caption'],
                                'share_to_feed': True})
        data['container'] = media_id(result)
        save('waiting for Instagram to process the video')
    for _ in range(60):
        status = api_json(session, 'GET', GRAPH + '/' + data['container'], 'Instagram',
                          params={'fields': 'status_code'}).get('status_code')
        if status == 'PUBLISHED':
            mark_instagram_published(publisher, session, record, None, save)
            return
        if status == 'FINISHED':
            break
        if status in ('ERROR', 'EXPIRED'):
            raise PublishError('Instagram could not process this video. Resume to retry the saved attempt.')
        if status != 'IN_PROGRESS':
            raise PublishError('Instagram returned an unknown processing state. Resume later to check it.')
        save('Instagram is processing the clip')
        time.sleep(5)
    else:
        raise PublishError('Instagram is still processing. Resume this saved attempt later.')
    data['publish_requested'] = True
    save('publishing the reviewed Reel')
    # Reuse this container on every retry; never create a second container after a publish attempt.
    try:
        result = api_json(session, 'POST', GRAPH + '/' + record['account'] + '/media_publish', 'Instagram',
                          json={'creation_id': data['container']})
    except PublishError:
        status = api_json(session, 'GET', GRAPH + '/' + data['container'], 'Instagram',
                          params={'fields': 'status_code'}).get('status_code')
        if status == 'PUBLISHED':
            mark_instagram_published(publisher, session, record, None, save)
            return
        raise
    mark_instagram_published(publisher, session, record, result, save)
