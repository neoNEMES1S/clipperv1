"""Validate and cache completed, publicly playable YouTube replays with yt-dlp."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from media import MissingToolError, validate_media

SUPPORTED_HOSTS = {
    'youtube.com', 'www.youtube.com', 'm.youtube.com',
    'youtube-nocookie.com', 'www.youtube-nocookie.com',
    'youtu.be', 'www.youtu.be',
}
VIDEO_SUFFIXES = {'.mkv', '.mp4', '.mov', '.ts', '.webm'}


def youtube_video_id(value: str) -> str:
    """Accept one video identity, never playlist/batch inputs or arbitrary hosts."""
    try:
        url = urlparse(value)
        if (url.scheme not in ('https', 'http') or url.hostname not in SUPPORTED_HOSTS
                or url.username or url.password or url.port not in (None, 80, 443)):
            raise ValueError('Unsupported YouTube URL')
        query = parse_qs(url.query, keep_blank_values=True)
        if 'list' in query:
            raise ValueError('Playlists are not supported; use a single video link without list=.')
        parts = url.path.strip('/').split('/')
        if url.hostname in {'youtu.be', 'www.youtu.be'} and len(parts) == 1:
            identity = parts[0]
        elif url.path == '/watch' and len(query.get('v', [])) == 1:
            identity = query['v'][0]
        elif len(parts) == 2 and parts[0] in {'live', 'embed', 'shorts'}:
            identity = parts[1]
        else:
            raise ValueError('Use a YouTube watch, live-replay, or youtu.be video URL.')
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', identity):
            raise ValueError('YouTube video IDs must contain exactly 11 letters, digits, _ or -.')
        return identity
    except ValueError as exc:
        raise ValueError(f'Invalid YouTube video URL: {exc}') from exc


def is_youtube_url(value: str) -> bool:
    try:
        youtube_video_id(value)
        return True
    except ValueError:
        return False


def is_web_url(value: str) -> bool:
    # Windows drive paths are local; all other URI schemes are remote inputs.
    return bool(re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', value)) and not bool(
        re.match(r'^[a-zA-Z]:[\\/]', value))


def download_youtube_video(url: str, cache_dir: Path) -> Path:
    identity = youtube_video_id(url)
    cache_dir = cache_dir.resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)

    def valid_files(root: Path) -> list[Path]:
        found = []
        for file in sorted(root.glob(identity + '.*')):
            if file.stem != identity or file.suffix.lower() not in VIDEO_SUFFIXES:
                continue
            try:
                validate_media(file)
            except MissingToolError:
                raise
            except (ValueError, RuntimeError) as exc:
                print(f'Ignoring invalid media {file}: {exc}')
            else:
                found.append(file)
        return found

    print('validate: checking saved replay...')
    cached = valid_files(cache_dir)
    if cached:
        print(f'download: using validated saved replay {cached[0]}; skipping download')
        return cached[0]
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise RuntimeError('Install yt-dlp first: pip install -r requirements.txt') from exc
    canonical = f'https://www.youtube.com/watch?v={identity}'
    settings = {'quiet': True, 'noplaylist': True,
                'js_runtimes': {'deno': {}, 'node': {}}}
    print('validate: checking YouTube replay status...')
    try:
        with YoutubeDL(settings) as ydl:
            info = ydl.extract_info(canonical, download=False)
    except Exception as exc:
        raise RuntimeError('YouTube metadata request failed. Check connectivity and replay availability; '
                           'private/removed/restricted videos are unsupported. If playable in your browser, '
                           f'update yt-dlp: python -m pip install -U "yt-dlp[default]". Details: {exc}') from exc
    if not isinstance(info, dict) or info.get('id') != identity or info.get('_type') in {'playlist', 'multi_video'}:
        raise RuntimeError('YouTube did not return metadata for the requested single video.')
    status = info.get('live_status')
    if status in {'is_live', 'is_upcoming', 'post_live'} or info.get('is_live') or info.get('is_upcoming'):
        raise RuntimeError(f'Stream status is {status!r}. Retry after the stream ends and its replay is ready.')
    if info.get('availability') in {'private', 'premium_only', 'subscriber_only', 'needs_auth'}:
        raise RuntimeError('Replay is private or restricted; use a publicly playable replay or a local recording.')
    # Keep partial files on failure so yt-dlp can resume; promote only validated media.
    staging = cache_dir / '_partial' / identity
    staging.mkdir(parents=True, exist_ok=True)
    settings.update({'format': 'bv+ba/b', 'outtmpl': str(staging / f'{identity}.%(ext)s'),
                     'merge_output_format': 'mkv', 'continuedl': True, 'overwrites': False})
    # A previous interrupted validation may have left a corrupt final container.
    ready = valid_files(staging)
    if not ready:
        for file in staging.glob(identity + '.*'):
            if file.stem == identity and file.suffix.lower() in VIDEO_SUFFIXES:
                file.unlink()
        print(f'download: fetching replay {identity}; ensure enough free disk space...')
        try:
            with YoutubeDL(settings) as ydl:
                ydl.extract_info(canonical, download=True)
        except Exception as exc:
            raise RuntimeError('YouTube download failed; partial files were retained for retry. Check network/HTTP '
                               'errors, free disk space, FFmpeg and Deno (or Node 22+) on PATH, and '
                               f'yt-dlp version. Details: {exc}') from exc
        ready = valid_files(staging)
    if not ready:
        raise RuntimeError('Download produced no valid video+audio container. Check FFmpeg, disk space and retry.')
    target = cache_dir / ready[0].name
    ready[0].replace(target)
    return target


def replay_signals(url: str, *, live: bool = False) -> list[tuple[float, float, float, str]]:
    """Return time windows and ranking weights from optional YouTube metadata."""
    import math
    from statistics import median
    import time

    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    canonical = f'https://www.youtube.com/watch?v={youtube_video_id(url)}'
    settings = {'quiet': True, 'no_warnings': True, 'noplaylist': True,
                'skip_download': True, 'socket_timeout': 10, 'retries': 0,
                'extractor_retries': 0, 'ignore_no_formats_error': True}
    samples = []
    windows = []
    failures = 0
    seen_live = False
    while True:
        try:
            with YoutubeDL(settings) as downloader:
                info = downloader.extract_info(canonical, download=False) or {}
        except DownloadError:
            if not live:
                print('audience: replay data unavailable; using footage signals.', flush=True)
                return []
            failures += 1
            if failures >= 5:
                raise ValueError('Could not read the live stream after five attempts. Try monitoring again.') from None
            print('live: Could not read YouTube metadata. Retrying in 60 seconds.', flush=True)
            time.sleep(60)
            continue
        failures = 0
        status = info.get('live_status')
        if live and status in ('is_live', 'is_upcoming'):
            seen_live |= status == 'is_live'
            count = info.get('concurrent_view_count')
            started = info.get('release_timestamp')
            now = time.time()
            if status == 'is_upcoming':
                print('live: Waiting for the broadcast to start.', flush=True)
            elif type(count) is int and count >= 0 and isinstance(started, (int, float)) and 0 < started <= now:
                elapsed = now - started
                samples = [(at, viewers) for at, viewers in samples if elapsed - 300 <= at < elapsed]
                baseline = median([viewers for _, viewers in samples]) if len(samples) >= 3 else None
                if baseline is not None and count - baseline >= max(5, baseline * .2):
                    windows.append((max(0, elapsed - 90), elapsed + 30, .8, 'live_viewer_spike'))
                    print(f'live: {count:,} viewers. Spike marked near {int(elapsed // 60)} min.', flush=True)
                else:
                    print(f'live: {count:,} viewers. Watching for spikes.', flush=True)
                samples.append((elapsed, count))
            else:
                print('live: Broadcast is active. Viewer count or start time is unavailable.', flush=True)
            time.sleep(60)
            continue
        if live and status == 'post_live':
            print('live: Broadcast ended. Waiting for YouTube to finish preparing the replay.', flush=True)
            time.sleep(60)
            continue
        if live and not seen_live and status != 'was_live':
            raise ValueError('Enter a live or upcoming YouTube stream, or use Replay mode.')
        break

    for item in info.get('heatmap') or []:
        if not isinstance(item, dict):
            continue
        start, end, score = (item.get(key) for key in ('start_time', 'end_time', 'value'))
        if (all(type(value) in (int, float) and math.isfinite(value) for value in (start, end, score))
                and 0 <= start < end and .5 <= score <= 1):
            windows.append((start, end, score * .6, 'most_replayed'))
    print(f'audience: {len(windows)} viewer-interest windows; ranking alongside footage signals.', flush=True)
    return windows
