import base64
import io
import json
from pathlib import Path
from urllib.error import URLError
from unittest.mock import Mock

import pytest

import clip_titles


@pytest.fixture
def vision(monkeypatch):
    def frame(args):
        Path(args[-1]).write_bytes(b'clip frame')

    monkeypatch.setattr(clip_titles, 'run', Mock(side_effect=frame))
    opener = Mock()
    factory = Mock(return_value=opener)
    monkeypatch.setattr(clip_titles, 'build_opener', factory)

    def reply(value):
        opener.open.return_value = io.BytesIO(json.dumps(value).encode())

    reply({'done': True, 'message': {'content': json.dumps({'title': 'Flying a plane in GTA 6'})}})
    return opener, factory, reply


def test_title_uses_clip_images_and_transcript_only_on_local_service(vision):
    opener, factory, _ = vision
    assert clip_titles.title_for_clip(Path('source.mkv'), 20, 36, 'Look at this plane!', 'gta6') == 'Flying a plane in GTA 6'
    request = opener.open.call_args.args[0]
    body = json.loads(request.data)
    assert request.full_url == 'http://127.0.0.1:11434/api/chat'
    assert factory.call_args.args[0].proxies == {}
    message = body['messages'][0]
    assert len(message['images']) == 4
    assert all(base64.b64decode(image) == b'clip frame' for image in message['images'])
    assert 'Look at this plane!' in message['content']
    assert body['model'] == clip_titles.TITLE_MODEL
    assert body['stream'] is False


@pytest.mark.parametrize('title', [None, '', ' ', 123, 'x' * 73, 'bad\x00title'])
def test_unclear_or_invalid_titles_are_rejected(vision, title):
    vision[2]({'done': True, 'message': {'content': json.dumps({'title': title})}})
    with pytest.raises(ValueError):
        clip_titles.title_for_clip(Path('source.mkv'), 0, 36, '', 'gta6')


@pytest.mark.parametrize('result', [
    {'done': False, 'message': {'content': '{"title":"A plane"}'}},
    {'done': True, 'done_reason': 'length', 'message': {'content': '{"title":"A plane"}'}},
    {'done': True, 'message': {'content': 'invalid JSON'}},
    {'done': True, 'message': {'content': '[]'}},
    {'done': True, 'message': {'content': ''}},
    {'done': True, 'message': None},
    {'done': True},
    [],
])
def test_incomplete_or_malformed_responses_are_rejected(vision, result):
    vision[2](result)
    with pytest.raises(ValueError):
        clip_titles.title_for_clip(Path('source.mkv'), 0, 36, '', 'gta6')


def test_unavailable_local_service_has_setup_message(vision):
    vision[0].open.side_effect = URLError('connection refused')
    with pytest.raises(RuntimeError, match='Start Ollama'):
        clip_titles.title_for_clip(Path('source.mkv'), 0, 36, '', 'fortnite')
