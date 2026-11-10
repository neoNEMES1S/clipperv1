import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

import clipper


@pytest.fixture
def job(tmp_path, monkeypatch):
    source = tmp_path / 'replay.mkv'
    source.write_bytes(b'source retained')
    output = tmp_path / 'shorts'
    info = {'format': {'duration': '120'},
            'streams': [{'codec_type': 'video'}, {'codec_type': 'audio'}]}
    monkeypatch.setattr(clipper, 'validate_media', Mock(return_value=info))
    monkeypatch.setattr(clipper, 'validate_short', Mock())
    monkeypatch.setattr(clipper, 'extract_audio', lambda video, dest, *args: dest.touch())
    levels = np.full(120, .02, dtype=np.float32)
    levels[30], levels[90] = .15, .16
    monkeypatch.setattr(clipper, 'energy_per_second', Mock(return_value=levels))
    render = Mock(side_effect=lambda video, target, *args: target.write_bytes(b'rendered'))
    monkeypatch.setattr(clipper, 'render_short', render)
    model = Mock()
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=model))
    return source, output, render, model


def run_job(job, **kwargs):
    source, output, _, _ = job
    return clipper.process(source, output, mic_track=0, no_transcribe=True, **kwargs)


def test_dry_run_is_analysis_only(job):
    report = run_job(job, dry_run=True, source_url='https://youtu.be/Abc123_-xyz')
    assert report['schema_version'] == '1.0'
    assert report['source']['video_id'] == 'Abc123_-xyz'
    assert report['source']['duration_seconds'] == 120
    assert report['status'] == 'created'
    assert len(report['candidates']) == 2
    assert report['shorts'] == []
    assert all(c['signals'] and c['score'] > 0 and c['evidence'] for c in report['candidates'])
    job[2].assert_not_called()
    job[3].assert_not_called()
    destination = clipper.Path(report['output_directory'])
    assert (destination / 'posting_notes.md').exists()
    assert 'select:' in (destination / 'processing.log').read_text()


def test_manifest_matches_outputs_and_rerun_reuses(job):
    first = run_job(job)
    assert first['status'] == 'review_required'
    assert all(s['status'] == 'review_required' for s in first['shorts'])
    assert job[2].call_count == 2
    again = run_job(job)
    assert first['output_directory'] == again['output_directory']
    assert job[2].call_count == 2
    destination = clipper.Path(first['output_directory'])
    for short in first['shorts']:
        assert (destination / short['path']).is_file()
        assert 0 <= short['start_seconds'] < short['end_seconds'] <= 120
    assert json.loads((destination / 'manifest.json').read_text())['status'] == 'review_required'


def test_configs_and_analysis_have_separate_directories(job):
    render = run_job(job)
    analysis = run_job(job, dry_run=True)
    alternate = run_job(job, pre_roll=20)
    assert len({r['output_directory'] for r in [render, analysis, alternate]}) == 3


def test_failure_persists_status_then_resumes(job):
    render = job[2]
    original = render.side_effect
    count = 0

    def fail_second(*args):
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError('encoder failed')
        original(*args)

    render.side_effect = fail_second
    with pytest.raises(RuntimeError, match='encoder failed'):
        run_job(job)
    destination = next(job[1].iterdir())
    report = json.loads((destination / 'manifest.json').read_text())
    assert report['status'] == 'failed'
    assert [s['status'] for s in report['shorts']] == ['review_required', 'failed']
    assert 'encoder failed' in (destination / 'processing.log').read_text()
    assert job[0].exists()
    render.side_effect = original
    again = run_job(job)
    assert again['status'] == 'review_required'
    assert render.call_count == 3  # Only the failed second clip was rendered on retry.


def test_zero_events_and_ocr_failure(job, monkeypatch):
    monkeypatch.setattr(clipper, 'energy_per_second', lambda path: np.zeros(120))
    monkeypatch.setattr(clipper, 'ocr_events', Mock(side_effect=RuntimeError('Tesseract missing')))
    report = run_job(job, use_ocr=True)
    assert report['status'] == 'created'
    assert report['shorts'] == report['candidates'] == []
    assert 'Tesseract missing' in report['warnings'][0]
    job[2].assert_not_called()
    job[3].assert_not_called()


def test_whisper_only_receives_selected_clip_audio(job, monkeypatch):
    monkeypatch.setattr(clipper, 'whisper_segments', Mock(return_value=[]))
    report = clipper.process(job[0], job[1], mic_track=0, max_shorts=1)
    assert len(report['shorts']) == 1
    assert report['shorts'][0]['transcript'] == ''
    assert report['shorts'][0]['captions'] == []
    assert clipper.whisper_segments.call_count == 1
    assert clipper.whisper_segments.call_args.args[0].name == 'short_01.wav'
    again = clipper.process(job[0], job[1], mic_track=0, max_shorts=1)
    assert again['warnings'] == report['warnings']
    assert clipper.whisper_segments.call_count == 1


def test_invalid_tracks_fail_before_extraction(job):
    with pytest.raises(ValueError, match='nonnegative'):
        clipper.process(job[0], job[1], mic_track=-1)


def test_analysis_failure_retains_successful_retry_metadata(job, monkeypatch):
    first = run_job(job)
    original = clipper.energy_per_second
    monkeypatch.setattr(clipper, 'energy_per_second', Mock(side_effect=RuntimeError('decode failed')))
    with pytest.raises(RuntimeError, match='decode failed'):
        run_job(job)
    manifest = clipper.Path(first['output_directory']) / 'manifest.json'
    failed = json.loads(manifest.read_text())
    assert failed['status'] == 'failed'
    assert [s['status'] for s in failed['shorts']] == ['review_required', 'review_required']
    monkeypatch.setattr(clipper, 'energy_per_second', original)
    run_job(job)
    assert job[2].call_count == 2


def test_missing_whisper_has_native_runtime_diagnostic(job, monkeypatch):
    monkeypatch.setitem(sys.modules, 'faster_whisper', None)
    with pytest.raises(RuntimeError, match='Visual C\\+\\+ x64 runtime'):
        clipper.process(job[0], job[1], mic_track=0, max_shorts=1)
    manifest = next(job[1].glob('*/manifest.json'))
    assert json.loads(manifest.read_text())['status'] == 'failed'
    assert job[0].exists()
