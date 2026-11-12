import io
import json
from pathlib import Path
import sys
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


@pytest.fixture
def workspace(tmp_path):
    workspace = app.Workspace(tmp_path / 'shorts')
    workspace.missing = []
    directory = workspace.output / 'Abc123_-xyz_123456789abc'
    directory.mkdir()
    (directory / 'short_01.mp4').write_bytes(bytes(range(256)))
    (directory / 'manifest.json').write_text(json.dumps({
        'source': {'video_id': 'Abc123_-xyz', 'url': 'https://youtu.be/Abc123_-xyz'},
        'config': {'combat_only': True}, 'status': 'review_required', 'warnings': [],
        'shorts': [{'path': 'short_01.mp4', 'status': 'review_required',
                    'start_seconds': 100, 'end_seconds': 136, 'captions': []}]
    }))
    return workspace


@pytest.fixture
def server(workspace):
    server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
    server.workspace = workspace
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def fetch(url, *, data=None, headers=None, method=None):
    try:
        return urlopen(Request(url, data=data, headers=headers or {}, method=method), timeout=3)
    except HTTPError as error:
        return error


def post(server, path, data, token):
    return fetch(server + path, data=json.dumps(data).encode(), headers={
        'Content-Type': 'application/json', 'X-Clipper-Token': token})


def test_state_and_bundled_page(server):
    with fetch(server + '/api/state') as response:
        data = json.load(response)
    assert data['app'] == 'clipper-local'
    assert len(data['runs']) == 1
    assert data['runs'][0]['clips'][0]['start'] == 100
    with fetch(server) as response:
        assert b'Generate clips' in response.read()
        assert "script-src 'self'" in response.headers['Content-Security-Policy']
    for asset in ('app.js', 'app.css'):
        with fetch(server + '/' + asset) as response:
            assert response.status == 200


@pytest.mark.parametrize('headers', [
    {'Host': 'evil.example'}, {'Origin': 'https://evil.example'},
])
def test_cross_site_access_is_denied(server, headers):
    with fetch(server + '/api/state', headers=headers) as response:
        assert response.status == 403


def test_start_requires_token_and_valid_options(server, workspace):
    with patch.object(workspace, 'start') as start:
        with post(server, '/api/start', {'url': 'https://youtu.be/Abc123_-xyz', 'max_clips': 25}, '') as response:
            assert response.status == 403
        start.assert_not_called()
        with post(server, '/api/start', {'url': 'https://youtu.be/Abc123_-xyz', 'max_clips': 25}, workspace.token) as response:
            assert response.status == 202
        start.assert_called_once_with('https://youtu.be/Abc123_-xyz', 25)


@pytest.mark.parametrize('url,maximum', [
    ('file:///etc/passwd', 25), ('https://evil.example/video', 25), (None, 25),
    ('https://youtu.be/Abc123_-xyz', 0), ('https://youtu.be/Abc123_-xyz', 101),
    ('https://youtu.be/Abc123_-xyz', True), ('https://youtu.be/Abc123_-xyz', 2.5),
])
def test_invalid_job_does_not_spawn(workspace, url, maximum):
    with patch('app.subprocess.Popen') as popen, pytest.raises(ValueError):
        workspace.start(url, maximum)
    popen.assert_not_called()


def test_start_preserves_pipeline_defaults_and_blocks_parallel_jobs(workspace):
    with patch('app.subprocess.Popen') as popen, patch('app.threading.Thread'):
        workspace.start('https://youtu.be/Abc123_-xyz?t=99', 25)
        with pytest.raises(RuntimeError, match='already processing'):
            workspace.start('https://youtu.be/Abc123_-xyz', 10)
        command = popen.call_args.args[0]
        assert command[0] == sys.executable
        assert command[command.index('--input') + 1] == 'https://www.youtube.com/watch?v=Abc123_-xyz'
        assert command[command.index('--max-shorts') + 1] == '25'
        assert '--combat-only' in command
        assert '--delete-download' not in command
        assert popen.call_args.kwargs.get('shell', False) is False
        assert popen.call_count == 1


@pytest.mark.parametrize('code,status', [(0, 'complete'), (1, 'failed')])
def test_worker_collects_real_progress_and_result(workspace, code, status):
    run = workspace.runs()[0]
    process = Mock(stdout=io.StringIO(f'render: short_01.mp4\ndone: {workspace.output / run["id"] / "manifest.json"}\n'))
    process.wait.return_value = code
    workspace.collect(process)
    assert workspace.job['status'] == status
    assert workspace.job['result_run'] == run['id']
    assert 'render: short_01.mp4' in workspace.lines


def test_missing_setup_does_not_spawn(workspace):
    workspace.missing = ['ffmpeg']
    with patch('app.subprocess.Popen') as popen, pytest.raises(ValueError, match='ffmpeg'):
        workspace.start('https://youtu.be/Abc123_-xyz', 25)
    popen.assert_not_called()


@pytest.mark.parametrize('requested,status,expected', [
    ('bytes=10-19', 206, bytes(range(10, 20))),
    ('bytes=250-', 206, bytes(range(250, 256))),
    ('bytes=-3', 206, bytes(range(253, 256))),
    ('bytes=256-', 416, b''), ('bytes=20-10', 416, b''),
    ('bytes=0-2,5-8', 416, b''),
])
def test_video_range_seeking(server, workspace, requested, status, expected):
    clip = workspace.runs()[0]['clips'][0]
    with fetch(server + clip['url'], headers={'Range': requested}) as response:
        assert response.status == status
        assert response.read() == expected
        assert 'Content-Range' in response.headers


def test_download_and_head(server, workspace):
    url = server + workspace.runs()[0]['clips'][0]['url']
    with fetch(url + '?download=1') as response:
        assert response.read() == bytes(range(256))
        assert 'attachment;' in response.headers['Content-Disposition']
    with fetch(url, method='HEAD') as response:
        assert response.status == 200
        assert response.read() == b''
        assert response.headers['Content-Length'] == '256'


def test_only_manifest_listed_completed_clips_are_served(server, workspace):
    run = workspace.runs()[0]
    directory = workspace.output / run['id']
    (directory / 'short_02.mp4').write_bytes(b'not completed')
    for path in ('/media/../app.py', '/media/%2e%2e/app.py',
                 f'/media/{run["id"]}/manifest.json', f'/media/{run["id"]}/short_02.mp4', '/app.py'):
        with fetch(server + path) as response:
            assert response.status == 404


def test_malformed_history_does_not_hide_good_results(workspace):
    bad = workspace.output / 'bad_run'
    bad.mkdir()
    (bad / 'manifest.json').write_text('{partial')
    assert len(workspace.runs()) == 1


def test_open_folder_restricted_to_known_runs(server, workspace):
    with patch('app.open_folder') as opener:
        with post(server, '/api/open-folder', {'run': '../../'}, workspace.token) as response:
            assert response.status == 404
        opener.assert_not_called()
        run = workspace.runs()[0]['id']
        with post(server, '/api/open-folder', {'run': run}, workspace.token) as response:
            assert response.status == 200
        opener.assert_called_once_with(workspace.output / run)


def test_symlinks_cannot_expose_files_outside_output(workspace, tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    try:
        (workspace.output / 'linked_run').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('This Windows account cannot create symlinks.')
    with pytest.raises(FileNotFoundError):
        workspace.run_directory('linked_run')


def test_shutdown_stops_the_owned_processing_tree(workspace):
    process = Mock(pid=123456)
    process.poll.return_value = None
    workspace.process = process
    with patch('app.os.killpg', create=True) as killpg, patch('app.subprocess.run') as run:
        workspace.close()
        if app.os.name == 'nt':
            run.assert_called_once_with(['taskkill', '/PID', '123456', '/T', '/F'], capture_output=True)
        else:
            killpg.assert_called_once_with(123456, app.signal.SIGTERM)
        process.wait.assert_called_once_with(timeout=5)
