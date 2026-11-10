import wave
from types import SimpleNamespace
from unittest.mock import Mock

from clipper import caption_chunks, escape_ass, hook_for, make_ass, whisper_segments


def test_special_characters_and_unicode(tmp_path):
    text = 'Hello, {world}! \\ नमस्ते 🎮\nNext'
    assert escape_ass(text) == 'Hello, \\{world\\}! \\\u2060 नमस्ते 🎮\\NNext'
    assert r'\N' not in escape_ass(r'\N')  # Literal text must not turn into an ASS line break.
    target = tmp_path / 'overlay.ass'
    make_ass(target, 'FORTNITE STREAM MOMENT', 3, [{'start': 0, 'end': 3, 'text': text}])
    assert escape_ass(text) in target.read_text(encoding='utf-8')


def test_bad_and_overlapping_timestamps_are_clamped(tmp_path):
    segments = [{'start': -2, 'end': 2, 'text': 'one two'},
                {'start': 1, 'end': 4, 'text': 'three four'},
                {'start': 5, 'end': 4, 'text': 'invalid'}]
    chunks = caption_chunks(segments)
    assert [(c['start'], c['end']) for c in chunks] == [(0, 2), (2, 4)]
    target = tmp_path / 'overlay.ass'
    make_ass(target, 'Headline', 3, chunks)
    assert '0:00:04.00' not in target.read_text()
    assert caption_chunks([]) == []


def test_long_words_fit_mobile_caption_width():
    chunks = caption_chunks([{'start': 0, 'end': 6, 'text': 'a' * 120}])
    assert len(chunks) == 4
    assert all(len(c['text']) <= 32 for c in chunks)


def test_whisper_uses_clip_duration_and_handles_empty(tmp_path):
    audio_path = tmp_path / 'clip.wav'
    with wave.open(str(audio_path), 'wb') as audio:
        audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\x00\x00' * 32000)
    model = Mock()
    quality = {'avg_logprob': -.2, 'compression_ratio': 1., 'no_speech_prob': .1}
    model.transcribe.return_value = (iter([
        SimpleNamespace(start=-1, end=1, text=' नमस्ते ', **quality),
        SimpleNamespace(start=.5, end=4, text='hello', **quality),
        SimpleNamespace(start=3, end=4, text='outside', **quality),
    ]), None)
    assert whisper_segments(audio_path, model) == [
        {'start': 0, 'end': 1, 'text': 'नमस्ते'}, {'start': 1, 'end': 2, 'text': 'hello'}]
    assert model.transcribe.call_args.kwargs['vad_filter'] is True
    assert model.transcribe.call_args.kwargs['temperature'] == 0
    model.transcribe.return_value = (iter([]), None)
    assert whisper_segments(audio_path, model) == []


def test_hook_does_not_claim_health_or_guaranteed_win():
    assert '1 HP' not in hook_for([], 'one hp!')
    assert hook_for(['victory_ocr'], '').startswith('POSSIBLE')


def test_unreliable_whisper_text_is_omitted(tmp_path):
    path = tmp_path / 'clip.wav'
    with wave.open(str(path), 'wb') as audio:
        audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\x00\x00' * 64000)
    quality = {'avg_logprob': -.2, 'compression_ratio': 1., 'no_speech_prob': .1}
    variants = [dict(quality, avg_logprob=-2), dict(quality, compression_ratio=8),
                dict(quality, no_speech_prob=.9), quality]
    segments = [SimpleNamespace(start=i, end=i+1, text='reliable' if i == 3 else 'bogus', **q)
                for i, q in enumerate(variants)]
    model = Mock()
    model.transcribe.return_value = (iter(segments), None)
    assert whisper_segments(path, model) == [{'start': 3, 'end': 4, 'text': 'reliable'}]
