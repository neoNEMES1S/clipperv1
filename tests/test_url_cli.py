import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import clipper


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.output = Path(temp.name) / 'out'

    @patch('clipper.process')
    @patch('youtube_source.download_youtube_video', return_value=Path('cached.mkv'))
    def test_youtube_input_uses_mixed_track(self, download_mock, process_mock):
        with patch.object(sys, 'argv', ['clipper.py', '--input', 'https://youtu.be/Abc123_-xyz', '--output', str(self.output)]):
            clipper.main()
        self.assertEqual(process_mock.call_args.args[2], 0)
        self.assertEqual(process_mock.call_args.kwargs['source_url'], 'https://youtu.be/Abc123_-xyz')
        download_mock.assert_called_once()

    @patch('clipper.process')
    def test_local_input_uses_mic_track_one(self, process_mock):
        with patch.object(sys, 'argv', ['clipper.py', '--input', 'local.mkv', '--output', str(self.output)]):
            clipper.main()
        self.assertEqual(process_mock.call_args.args[2], 1)
        self.assertIsNone(process_mock.call_args.kwargs['source_url'])

    @patch('clipper.process', side_effect=RuntimeError('render failed'))
    @patch('youtube_source.download_youtube_video', return_value=Path('cached.mkv'))
    @patch.object(Path, 'unlink')
    def test_failed_job_never_deletes_source(self, unlink, download, process):
        with patch.object(sys, 'argv', ['clipper.py', '--input', 'https://youtu.be/Abc123_-xyz',
                                       '--output', str(self.output), '--delete-download']):
            with self.assertRaises(SystemExit) as raised:
                clipper.main()
        self.assertEqual(raised.exception.code, 1)
        unlink.assert_not_called()

    @patch('clipper.process')
    @patch('youtube_source.download_youtube_video', return_value=Path('cached.mkv'))
    @patch.object(Path, 'unlink')
    def test_dry_run_never_deletes_source(self, unlink, download, process):
        with patch.object(sys, 'argv', ['clipper.py', '--input', 'https://youtu.be/Abc123_-xyz',
                                       '--output', str(self.output), '--delete-download', '--dry-run']):
            clipper.main()
        unlink.assert_not_called()

    @patch('youtube_source.download_youtube_video')
    def test_invalid_settings_rejected_before_download(self, download):
        for extra in [['--max-shorts', '-1'], ['--peak-ratio', 'nan'], ['--mic-track', '-1']]:
            with self.subTest(extra=extra):
                with patch.object(sys, 'argv', ['clipper.py', '--input', 'https://youtu.be/Abc123_-xyz',
                                               '--output', str(self.output)] + extra):
                    with self.assertRaises(SystemExit):
                        clipper.main()
        download.assert_not_called()

    @patch('clipper.process')
    @patch('youtube_source.download_youtube_video', return_value=Path('cached.mkv'))
    @patch.object(Path, 'unlink')
    def test_successful_job_deletes_only_when_requested(self, unlink, download, process):
        with patch.object(sys, 'argv', ['clipper.py', '--input', 'https://youtu.be/Abc123_-xyz',
                                       '--output', str(self.output), '--delete-download']):
            clipper.main()
        unlink.assert_called_once_with()

    @patch('clipper.process')
    @patch.object(Path, 'unlink')
    def test_delete_flag_never_deletes_local_input(self, unlink, process):
        with patch.object(sys, 'argv', ['clipper.py', '--input', 'recording.mkv',
                                       '--output', str(self.output), '--delete-download']):
            clipper.main()
        unlink.assert_not_called()

    @patch('youtube_source.download_youtube_video', side_effect=KeyboardInterrupt)
    @patch.object(Path, 'unlink')
    def test_interrupted_download_is_clear_and_retained(self, unlink, download):
        with patch.object(sys, 'argv', ['clipper.py', '--input', 'https://youtu.be/Abc123_-xyz',
                                       '--output', str(self.output), '--delete-download']):
            with self.assertRaises(SystemExit) as raised:
                clipper.main()
        self.assertEqual(raised.exception.code, 130)
        unlink.assert_not_called()

    @patch('clipper.process')
    def test_combat_selection_flag_is_forwarded(self, process):
        with patch.object(sys, 'argv', ['clipper.py','--input','local.mkv',
                                       '--output',str(self.output),'--combat-only']):
            clipper.main()
        self.assertTrue(process.call_args.kwargs['combat_only'])


if __name__ == '__main__':
    unittest.main()
