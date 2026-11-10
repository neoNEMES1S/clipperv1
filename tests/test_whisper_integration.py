"""Opt-in checks using real local model weights and the upstream JFK speech sample."""
import os
import shutil
from pathlib import Path

import pytest

from clipper import whisper_segments
from media import run

MODEL = os.environ.get('CLIPPER_WHISPER_MODEL')
SPEECH = os.environ.get('CLIPPER_SPEECH_SAMPLE')
pytestmark = pytest.mark.skipif(
    not MODEL or not SPEECH or not shutil.which('ffmpeg'),
    reason='Set CLIPPER_WHISPER_MODEL and CLIPPER_SPEECH_SAMPLE (upstream JFK sample) for real Whisper checks',
)


@pytest.fixture(scope='module')
def model():
    from faster_whisper import WhisperModel
    assert Path(MODEL).is_dir(), 'Download local model weights before running integration checks'
    assert Path(SPEECH).is_file(), 'Download the upstream JFK speech sample first'
    return WhisperModel(MODEL, device='cpu', compute_type='int8')


def test_actual_speech_has_valid_clip_relative_timestamps(model, tmp_path):
    audio = tmp_path / 'speech.wav'
    run(['ffmpeg', '-v', 'error', '-y', '-i', SPEECH, '-ac', '1', '-ar', '16000', str(audio)])
    segments = whisper_segments(audio, model)
    assert segments and 'country' in ' '.join(s['text'].lower() for s in segments)
    previous_end = 0.
    for segment in segments:
        assert previous_end <= segment['start'] < segment['end'] <= 11.1
        previous_end = segment['end']


def test_actual_silence_has_no_fabricated_captions(model, tmp_path):
    audio = tmp_path / 'silence.wav'
    run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=16000:cl=mono',
         '-t', '10', str(audio)])
    assert whisper_segments(audio, model) == []
