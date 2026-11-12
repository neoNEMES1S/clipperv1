import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edit_clip import edit_headline, normalize_headline


@pytest.fixture
def draft(tmp_path):
    directory = tmp_path / 'draft_run'
    directory.mkdir()
    source = tmp_path / 'source.mkv'
    source.write_bytes(b'original source')
    target = directory / 'short_01.mp4'
    target.write_bytes(b'original draft')
    report = {'status': 'review_required', 'source': {'path': str(source)},
              'config': {'mix_track': 0}, 'warnings': [], 'shorts': [{
                  'id': 'short_01', 'path': target.name, 'status': 'review_required',
                  'title': 'OLD #Fortnite #Shorts', 'description': 'Draft', 'transcript': 'hello',
                  'start_seconds': 42, 'end_seconds': 78,
                  'captions': [{'start': 0, 'end': 1, 'text': 'hello'}]}]}
    (directory / 'manifest.json').write_text(json.dumps(report))
    return directory, target, report


@pytest.mark.parametrize('text,expected', [('  My  fight! ', 'My fight!'), ('', ''),
                                          ('नमस्ते', 'नमस्ते'), ('--literal', '--literal')])
def test_normalize_headline(text, expected):
    assert normalize_headline(text) == expected


@pytest.mark.parametrize('text', [None, 12, 'a\x00b', 'x' * 73, 'thirteenchars ' * 5])
def test_reject_invalid_or_overflowing_headlines(text):
    with pytest.raises(ValueError):
        normalize_headline(text)


def test_edit_updates_only_one_clip_and_preserves_original_and_captions(draft):
    directory, target, report = draft
    overlays = []

    def render(source, output, ass, start, duration, track):
        assert (start, duration, track) == (42, 36, 0)
        assert source == Path(report['source']['path'])
        overlays.append(ass.read_text())
        output.write_bytes(b'edited clip')

    with patch('clipper.render_short', side_effect=render):
        edit_headline(directory.parent, directory.name, target.name, 'NEW {title}')
        edit_headline(directory.parent, directory.name, target.name, '')
    updated = json.loads((directory / 'manifest.json').read_text())
    assert target.read_bytes() == b'edited clip'
    assert (directory / 'short_01.original.mp4').read_bytes() == b'original draft'
    assert updated['shorts'][0]['headline'] == ''
    assert updated['shorts'][0]['captions'] == report['shorts'][0]['captions']
    assert updated['source'] == report['source']
    assert updated['config'] == report['config']
    assert 'NEW \\{title\\}' in overlays[0]
    assert 'Caption' in overlays[0] and 'hello' in overlays[0]
    assert not list(directory.glob('*.partial.mp4'))


def test_render_failure_preserves_video_and_manifest(draft):
    directory, target, report = draft
    before = (directory / 'manifest.json').read_bytes()
    with patch('clipper.render_short', side_effect=RuntimeError('encoder failed')):
        with pytest.raises(RuntimeError):
            edit_headline(directory.parent, directory.name, target.name, 'NEW')
    assert target.read_bytes() == b'original draft'
    assert (directory / 'manifest.json').read_bytes() == before


def test_missing_source_is_rejected_before_render(draft):
    directory, target, report = draft
    Path(report['source']['path']).unlink()
    with patch('clipper.render_short') as render, pytest.raises(ValueError, match='original replay'):
        edit_headline(directory.parent, directory.name, target.name, 'NEW')
    render.assert_not_called()


@pytest.mark.parametrize('run,name', [('../outside', 'short_01.mp4'),
                                      ('draft_run', '../source.mkv'), ('draft_run', 'short_02.mp4')])
def test_edit_rejects_other_paths_and_unlisted_clips(draft, run, name):
    directory, _, _ = draft
    with patch('clipper.render_short') as render, pytest.raises(ValueError):
        edit_headline(directory.parent, run, name, 'NEW')
    render.assert_not_called()
