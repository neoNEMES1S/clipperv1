import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from youtube_source import download_youtube_video, is_youtube_url, is_web_url
from media import MissingToolError

class YoutubeUrlTests(unittest.TestCase):
    def test_valid_video_links(self):
        for url in [
            'https://www.youtube.com/watch?v=Abc123_-xyz',
            'https://youtube.com/live/Abc123_-xyz',
            'https://youtu.be/Abc123_-xyz?t=20',
            'https://m.youtube.com/watch?v=Abc123_-xyz',
        ]:
            with self.subTest(url=url):
                self.assertTrue(is_youtube_url(url))

    def test_fake_domains_rejected(self):
        for url in [
            'https://youtube.com.evil.example/watch?v=abc',
            'https://evil.example/youtube.com/watch?v=abc',
            'file:///tmp/test.mp4',
            'https://youtube.com',
            'not_a_video.mp4',
            'https://youtube.com/watch?v=abc123_-.',
            'https://youtube.com/watch?v=Abc123_-xyz&list=PL123',
            'https://youtube.com/playlist?list=PL123',
            'https://youtu.be/Abc123_-xyz/extra',
            'ftp://youtube.com/watch?v=Abc123_-xyz',
            'https://user@youtube.com/watch?v=Abc123_-xyz',
            'https://youtube.com/watch?v=Abc123_-xyz&v=Abc123_-xyz',
        ]:
            with self.subTest(url=url):
                self.assertFalse(is_youtube_url(url))

    def test_web_url(self):
        self.assertTrue(is_web_url('https://example.com/video'))
        self.assertFalse(is_web_url('D:\\Videos\\stream.mkv'))


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name)
        self.identity = 'Abc123_-xyz'
        self.url = f'https://youtu.be/{self.identity}'
        self.info = {'id': self.identity, 'live_status': 'was_live'}
        self.downloads = 0
        self.error = None
        self.metadata_error = None
        self.settings_seen = []
        owner = self

        class FakeDL:
            def __init__(self, settings):
                self.settings = dict(settings)
                owner.settings_seen.append(self.settings)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def extract_info(self, url, download):
                if not download and owner.metadata_error:
                    raise owner.metadata_error
                if download:
                    owner.downloads += 1
                    target = Path(self.settings['outtmpl'].replace('%(ext)s', 'mkv'))
                    if owner.error:
                        target.with_suffix('.mkv.part').write_bytes(b'partial')
                        raise owner.error
                    target.write_bytes(b'valid')
                return owner.info

        self.addCleanup(patch.stopall)
        patch.dict(sys.modules, {'yt_dlp': SimpleNamespace(YoutubeDL=FakeDL)}).start()

        def validate(path):
            if path.read_bytes() != b'valid':
                raise ValueError('corrupt')

        patch('youtube_source.validate_media', side_effect=validate).start()

    def test_completed_download_then_reuse(self):
        first = download_youtube_video(self.url, self.cache)
        self.assertEqual(first.read_bytes(), b'valid')
        self.assertEqual(download_youtube_video(self.url, self.cache), first)
        self.assertEqual(self.downloads, 1)
        self.assertEqual(self.settings_seen[0]['js_runtimes'], {'deno': {}, 'node': {}})

    def test_corrupt_cache_redownloaded(self):
        (self.cache / f'{self.identity}.mkv').write_bytes(b'corrupt')
        self.assertEqual(download_youtube_video(self.url, self.cache).read_bytes(), b'valid')
        self.assertEqual(self.downloads, 1)

    def test_unready_replays_rejected(self):
        for status in ['is_live', 'is_upcoming', 'post_live']:
            with self.subTest(status=status):
                self.info['live_status'] = status
                with self.assertRaisesRegex(RuntimeError, 'replay is ready'):
                    download_youtube_video(self.url, self.cache)
        self.assertEqual(self.downloads, 0)

    def test_private_and_missing_metadata(self):
        self.info['availability'] = 'private'
        with self.assertRaisesRegex(RuntimeError, 'private or restricted'):
            download_youtube_video(self.url, self.cache)
        self.info = None
        with self.assertRaisesRegex(RuntimeError, 'metadata'):
            download_youtube_video(self.url, self.cache)

    def test_failure_keeps_partial_out_of_complete_cache(self):
        self.error = OSError('HTTP 503')
        with self.assertRaisesRegex(RuntimeError, 'HTTP 503'):
            download_youtube_video(self.url, self.cache)
        self.assertFalse((self.cache / f'{self.identity}.mkv').exists())
        self.assertTrue(list((self.cache / '_partial').rglob('*.part')))

    def test_invalid_download_never_promoted(self):
        with patch('youtube_source.validate_media', side_effect=ValueError('no audio')):
            with self.assertRaisesRegex(RuntimeError, 'no valid video'):
                download_youtube_video(self.url, self.cache)
        self.assertFalse((self.cache / f'{self.identity}.mkv').exists())

    def test_metadata_error_is_actionable(self):
        self.metadata_error = RuntimeError('video removed')
        with self.assertRaisesRegex(RuntimeError, 'Check connectivity.*video removed'):
            download_youtube_video(self.url, self.cache)
        self.assertEqual(self.downloads, 0)

    def test_missing_probe_never_removes_cached_media(self):
        target = self.cache / f'{self.identity}.mkv'
        target.write_bytes(b'valid')
        with patch('youtube_source.validate_media', side_effect=MissingToolError('ffprobe missing')):
            with self.assertRaisesRegex(RuntimeError, 'ffprobe missing'):
                download_youtube_video(self.url, self.cache)
        self.assertEqual(target.read_bytes(), b'valid')
        self.assertEqual(self.downloads, 0)

    def test_partial_video_components_are_preserved(self):
        staging = self.cache / '_partial' / self.identity
        staging.mkdir(parents=True)
        component = staging / f'{self.identity}.f137.mp4'
        component.write_bytes(b'video-only component')
        download_youtube_video(self.url, self.cache)
        self.assertTrue(component.exists())

if __name__ == '__main__':
    unittest.main()
