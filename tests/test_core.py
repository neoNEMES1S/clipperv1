import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from clipper import Event, ass_time, caption_chunks, microphone_events, select_clips


class CoreTests(unittest.TestCase):
    def test_reaction_peak(self):
        signal = np.full(90, .022, dtype=np.float32)
        signal[35] = .15
        signal[72] = .17
        found = microphone_events(signal)
        self.assertEqual([int(s.time) for s in found], [35, 72])

    def test_non_overlapping_highlights(self):
        events = [Event(30, 3, 'mic_reaction'), Event(34, 6, 'victory_ocr'),
                  Event(96, 4, 'mic_reaction')]
        clips = select_clips(events, 150, 2)
        self.assertEqual(len(clips), 2)
        self.assertLess(clips[0].start, clips[1].start)
        self.assertIn('victory_ocr', clips[0].signals)

    def test_timing_and_subtitles(self):
        self.assertEqual(ass_time(61.23), '0:01:01.23')
        chunks = caption_chunks([{'start': 0, 'end': 4, 'text': 'one two three four five six'}])
        self.assertEqual(len(chunks), 2)
        self.assertAlmostEqual(chunks[0]['end'], 2.)


if __name__ == '__main__':
    unittest.main()
