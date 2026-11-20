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


def test_combat_mode_requires_visual_events_and_records_them(job, monkeypatch):
    monkeypatch.setattr(clipper, 'combat_events', Mock(return_value=[
        clipper.Event(60,4.5,'kill_counter_change',1.,'Personal HUD 0 -> 1, stable')]))
    report = run_job(job, combat_only=True, dry_run=True)
    assert report['config']['combat_only'] is True
    assert len(report['candidates']) == 1
    assert report['candidates'][0]['anchor'] == 60
    assert 'kill_counter_change' in report['candidates'][0]['signals']


def test_combat_scan_failure_does_not_fall_back_to_talking(job, monkeypatch):
    monkeypatch.setattr(clipper, 'combat_events', Mock(side_effect=RuntimeError('OCR missing')))
    with pytest.raises(RuntimeError, match='OCR missing'):
        run_job(job, combat_only=True)
    manifest = next(job[1].glob('*/manifest.json'))
    report = json.loads(manifest.read_text())
    assert report['status'] == 'failed'
    assert report['shorts'] == []
    job[2].assert_not_called()


def test_gta6_uses_audio_and_game_specific_posting_text(job, monkeypatch):
    combat = Mock(side_effect=AssertionError('Fortnite detector must not run for GTA 6'))
    monkeypatch.setattr(clipper, 'combat_events', combat)
    fortnite = run_job(job)
    gta = run_job(job, game='gta6')
    assert gta['output_directory'] != fortnite['output_directory']
    assert gta['config']['game'] == 'gta6'
    assert gta['config']['combat_only'] is False
    assert len(gta['shorts']) == 2
    for short in gta['shorts']:
        assert short['signals'] == ['mic_reaction']
        assert short['headline'] == 'GTA 6 STREAM MOMENT'
        assert '#GTA6' in short['title']
        assert 'GTA 6 stream' in short['description']
        assert 'Fortnite' not in short['title'] + short['description']
    combat.assert_not_called()


@pytest.mark.parametrize('options', [{'combat_only': True}, {'use_ocr': True}, {'game': 'unknown'}])
def test_invalid_game_settings_rejected_before_processing(job, options):
    with pytest.raises(ValueError):
        run_job(job, **({'game': 'gta6'} | options))
    job[2].assert_not_called()


def test_zero_combat_candidates_explain_game_selection(job, monkeypatch, capsys):
    monkeypatch.setattr(clipper, 'combat_events', Mock(return_value=[]))
    report = run_job(job, combat_only=True, dry_run=True)
    assert report['candidates'] == []
    assert 'For GTA 6 footage, choose GTA 6' in capsys.readouterr().out


def test_automatic_title_uses_transcript_and_reaches_video_and_posting(job, monkeypatch):
    title = 'Flying a plane in GTA 6'
    vision = Mock(return_value=title)
    monkeypatch.setattr(clipper, 'title_for_clip', vision)
    monkeypatch.setattr(clipper, 'whisper_segments', Mock(return_value=[
        {'start': 0, 'end': 1, 'text': 'Look at this plane!'}]))
    overlay = Mock(wraps=clipper.make_ass)
    monkeypatch.setattr(clipper, 'make_ass', overlay)
    report = clipper.process(job[0], job[1], mic_track=0, max_shorts=1, game='gta6', auto_title=True)
    short = report['shorts'][0]
    assert short['headline'] == title
    assert short['title'] == f'{title} #GTA6 #Shorts'
    assert report['config']['title_model'] == clipper.TITLE_MODEL
    assert vision.call_args.args[3:] == ('Look at this plane!', 'gta6')
    assert overlay.call_args.args[1] == title
    manifest = clipper.Path(report['output_directory']) / 'manifest.json'
    short['headline'], short['title'] = 'My own title', 'My own title #GTA6 #Shorts'
    manifest.write_text(json.dumps(report))
    again = clipper.process(job[0], job[1], mic_track=0, max_shorts=1, game='gta6', auto_title=True)
    assert again['shorts'][0]['headline'] == 'My own title'
    assert vision.call_count == 1
    assert job[2].call_count == 1


def test_title_failure_keeps_generic_title_and_renders(job, monkeypatch):
    monkeypatch.setattr(clipper, 'title_for_clip', Mock(side_effect=RuntimeError('Ollama unavailable')))
    report = run_job(job, game='gta6', auto_title=True, max_shorts=1)
    assert report['status'] == 'review_required'
    assert report['shorts'][0]['headline'] == 'GTA 6 STREAM MOMENT'
    assert any('automatic title unavailable' in warning for warning in report['warnings'])
    assert job[2].call_count == 1


def test_dry_run_never_calls_vision_model(job, monkeypatch):
    vision = Mock()
    monkeypatch.setattr(clipper, 'title_for_clip', vision)
    run_job(job, game='gta6', auto_title=True, dry_run=True)
    vision.assert_not_called()
