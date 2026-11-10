from pathlib import Path
from unittest.mock import patch

import pytest

from media import validate_media


@pytest.mark.parametrize('duration,streams', [
    ('0', ['video', 'audio']), ('nan', ['video', 'audio']),
    ('inf', ['video', 'audio']), ('10', ['video']), ('10', ['audio']),
])
def test_reject_unusable_media(tmp_path, duration, streams):
    source = tmp_path / 'source.mkv'
    source.write_bytes(b'not-empty')
    info = {'format': {'duration': duration}, 'streams': [{'codec_type': s} for s in streams]}
    with patch('media.probe', return_value=info), pytest.raises(ValueError):
        validate_media(source)


def test_missing_media():
    with pytest.raises(ValueError, match='missing or empty'):
        validate_media(Path('/nonexistent/replay.mkv'))
