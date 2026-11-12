"""Local browser interface for the existing clipper CLI; no web dependencies."""
from __future__ import annotations

import argparse
from collections import deque
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

from youtube_source import youtube_video_id

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / 'web'


def pipeline_environment() -> dict[str, str]:
    env = os.environ.copy()
    env['PATH'] = os.pathsep.join([str(ROOT / '.local' / 'bin'), str(Path(sys.executable).parent),
                                  '/opt/homebrew/bin', '/usr/local/bin', env.get('PATH', '')])
    env['PYTHONUNBUFFERED'] = '1'
    return env


class Workspace:
    def __init__(self, output: Path):
        self.output = output.resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.job = {'status': 'idle', 'url': '', 'max_clips': 25, 'result_run': None}
        self.lines: deque[str] = deque(maxlen=150)
        self.process: subprocess.Popen | None = None
        self.env = pipeline_environment()
        self.missing = [name for name in ('ffmpeg', 'ffprobe')
                        if not shutil.which(name, path=self.env['PATH'])]
        self.missing += [name for name in ('numpy', 'faster_whisper', 'rapidocr_onnxruntime')
                         if importlib.util.find_spec(name) is None]

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
            clips.append({'name': name, 'start': start, 'end': end,
                          'title': str(clip.get('title', 'Draft clip')),
                          'captions': bool(clip.get('captions')),
                          'url': f'/media/{identity}/{name}'})
        source = data.get('source', {})
        return {'id': identity, 'revision': manifest.stat().st_mtime_ns,
                'source_id': source.get('video_id') or identity,
                'source_url': source.get('url'), 'status': data.get('status', 'unknown'),
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

    def snapshot(self) -> dict:
        with self.lock:
            job = dict(self.job, log=list(self.lines))
        return {'app': 'clipper-local', 'token': self.token, 'job': job,
                'runs': self.runs(), 'missing': self.missing}

    def start(self, url: str, maximum: int) -> None:
        if not isinstance(url, str) or len(url) > 2048:
            raise ValueError('Paste a completed YouTube replay URL.')
        identity = youtube_video_id(url.strip())
        if type(maximum) is not int or not 1 <= maximum <= 100:
            raise ValueError('Choose a clip limit between 1 and 100.')
        if self.missing:
            raise ValueError('Setup needed: missing ' + ', '.join(self.missing) + '. See README setup instructions.')
        canonical = f'https://www.youtube.com/watch?v={identity}'
        model = 'models/small' if (ROOT / 'models' / 'small' / 'model.bin').is_file() else 'small'
        command = [sys.executable, '-u', str(ROOT / 'clipper.py'), '--input', canonical,
                   '--output', str(self.output), '--max-shorts', str(maximum), '--model', model,
                   '--combat-only', '--pre-roll', '28', '--post-roll', '8']
        with self.lock:
            if self.job['status'] == 'running':
                raise RuntimeError('A replay is already processing. Wait for it to finish.')
            options = ({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt'
                       else {'start_new_session': True})
            self.process = subprocess.Popen(command, cwd=ROOT, env=self.env, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                            errors='replace', bufsize=1, **options)
            self.job = {'status': 'running', 'url': canonical, 'max_clips': maximum, 'result_run': None}
            self.lines.clear()
            self.lines.append('Starting replay processing…')
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
                self.job['status'] = 'complete' if code == 0 else 'failed'
                if code:
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
            elif path in ('/', '/app.css', '/app.js'):
                name, kind = {'/': ('index.html', 'text/html; charset=utf-8'),
                              '/app.css': ('app.css', 'text/css; charset=utf-8'),
                              '/app.js': ('app.js', 'text/javascript; charset=utf-8')}[path]
                body = (ASSETS / name).read_bytes()
                self.response_headers(200, kind, len(body))
                if self.command != 'HEAD':
                    self.wfile.write(body)
            elif path.startswith('/media/'):
                parts = path.split('/')
                if len(parts) != 4:
                    raise FileNotFoundError('Clip not found.')
                run = self.workspace.read_run(parts[2])
                if not any(c['name'] == parts[3] for c in run['clips']):
                    raise FileNotFoundError('Clip not found.')
                file = self.workspace.run_directory(parts[2]) / parts[3]
                self.media(file, parse_qs(target.query).get('download') == ['1'])
            elif path == '/favicon.ico':
                self.response_headers(204, 'image/x-icon', 0)
            else:
                raise FileNotFoundError('Page not found.')
        except (FileNotFoundError, ValueError, KeyError, TypeError):
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
            if not 0 < length <= 4096 or self.headers.get_content_type() != 'application/json':
                raise ValueError('Expected a small JSON request.')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Expected an object.')
            if self.path == '/api/start':
                self.workspace.start(data.get('url'), data.get('max_clips'))
                self.json_response({'status': 'running'}, 202)
            elif self.path == '/api/open-folder':
                open_folder(self.workspace.run_directory(data.get('run', '')))
                self.json_response({'status': 'opened'})
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
