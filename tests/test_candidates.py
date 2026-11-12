import wave

import numpy as np
import pytest

from clipper import Event, energy_per_second, kill_counter_events, microphone_events, select_clips


def test_chunked_synthetic_audio(tmp_path):
    path = tmp_path / 'peaks.wav'
    rate = 16000
    with wave.open(str(path), 'wb') as audio:
        audio.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        for second in range(90):
            volume = .3 if second in (25, 70) else .025
            samples = volume * np.sin(2 * np.pi * 440 * np.arange(rate) / rate)
            audio.writeframes((samples * 32767).astype('<i2').tobytes())
    events = microphone_events(energy_per_second(path))
    assert [e.time for e in events] == [25, 70]
    assert all(0 < e.metadata()['normalized_score'] <= 1 for e in events)
    assert all(e.metadata()['evidence'] for e in events)


@pytest.mark.parametrize('volume', [0, .004, .03, .5])
def test_constant_input_has_no_events(volume):
    assert microphone_events(np.full(120, volume, dtype=np.float32)) == []


def test_windows_clamp_and_reject_short_sources():
    events = [Event(0, 4, 'mic_reaction'), Event(99, 5, 'mic_reaction')]
    clips = select_clips(events, 100, 3)
    assert [(c.start, c.end) for c in clips] == [(0, 13), (76, 100)]
    assert select_clips([Event(1, 5, 'mic_reaction')], 5, 3) == []
    assert select_clips(events, 100, 0) == []
    assert select_clips([], 100, 3) == []


def test_multisignal_beats_repeated_same_signal():
    single = [Event(30, 5, 'mic_reaction'), Event(31, 5, 'mic_reaction')]
    multi = [Event(90, 5, 'mic_reaction'), Event(92, 5, 'elimination_ocr')]
    clips = select_clips(single + multi, 130, 1)
    assert len(clips) == 1
    assert clips[0].anchor >= 90
    assert clips[0].signals == ['elimination_ocr', 'mic_reaction']


def test_selection_is_deterministic_and_distinct():
    events = [Event(t, 4, 'mic_reaction') for t in [35, 32, 31, 100, 140]]
    clips = select_clips(events, 180, 3)
    assert clips == select_clips(list(reversed(events)), 180, 3)
    for i, clip in enumerate(clips):
        assert all(min(clip.end, other.end) - max(clip.start, other.start) <= 4
                   for other in clips[i + 1:])


def test_stronger_peaks_are_not_flattened_into_early_ties():
    levels = np.full(240, .01, dtype=np.float32)
    levels[30], levels[110], levels[200] = .12, .3, .6
    events = microphone_events(levels)
    strengths = [e.metadata()['normalized_score'] for e in events]
    assert strengths[0] < strengths[1] < strengths[2] < 1
    assert select_clips(events, 240, 1)[0].anchor == 200


def test_counter_requires_stability_and_ignores_initial_counts_and_resets():
    values = [3, 3, 4, 4, 4, 0, 0, 1, 1, 8, 8]
    readings = [{'time':float(i * 2), 'count':n, 'confidence':.98} for i,n in enumerate(values)]
    events = kill_counter_events(readings)
    assert [(e.time,e.raw_score) for e in events] == [(4.,1.), (14.,1.)]
    assert all('two agreeing reads' in e.evidence for e in events)


def test_counter_ignores_transient_or_uncertain_ocr():
    readings = [{'time':float(i * 2), 'count':n, 'confidence':confidence}
                for i,(n,confidence) in enumerate([(0,.99),(0,.99),(2,.99),(0,.99),
                                                   (0,.99),(1,.79),(1,.79),(None,0)])]
    assert kill_counter_events(readings) == []


def test_counter_after_a_hud_gap_establishes_new_baseline():
    readings = [{'time':t,'count':n,'confidence':.99} for t,n in [(0,0),(2,0),(40,2),(42,2)]]
    assert kill_counter_events(readings) == []


def test_counter_preserves_quad_wipes():
    readings = [{'time':float(i*2),'count':n,'confidence':.99} for i,n in enumerate([0,0,4,4])]
    events = kill_counter_events(readings)
    assert len(events)==1 and events[0].raw_score==4


def test_combat_mode_never_anchors_on_talk_or_general_kill_feed():
    talk = [Event(30, 100, 'mic_reaction'), Event(90, 5.5, 'elimination_ocr')]
    assert select_clips(talk, 150, 3, combat_only=True) == []
    kills = [Event(120, 4.5, 'kill_counter_change', 1., '0 -> 1, two reads')]
    clips = select_clips(talk+kills, 150, 3, combat_only=True)
    assert len(clips) == 1
    assert clips[0].anchor == 120
    assert 'kill_counter_change' in clips[0].signals


def test_combat_mode_prefers_multi_kill_over_louder_talking():
    events = [Event(40, 4.5, 'kill_counter_change', 1.), Event(40, 100, 'mic_reaction'),
              Event(110, 4.5, 'kill_counter_change', 1.), Event(116, 4.5, 'kill_counter_change', 1.)]
    assert select_clips(events, 160, 1, combat_only=True)[0].anchor >= 110
