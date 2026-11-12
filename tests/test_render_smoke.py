"""Offline integration tests; no replay downloads or Whisper weights required."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from clipper import energy_per_second, extract_audio, make_ass, render_short
from media import probe, run, validate_media

pytestmark = pytest.mark.skipif(
    not shutil.which('ffmpeg') or not shutil.which('ffprobe'),
    reason='FFmpeg and FFprobe are required for synthetic media smoke tests',
)


@pytest.fixture(scope='module')
def source(tmp_path_factory):
    root = tmp_path_factory.mktemp('synthetic_media')
    target = root / 'test.mkv'
    run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
         '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=30',
         '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=16000',
         '-af', "volume='if(between(t,6,7),1,0.08)':eval=frame",
         '-t', '12', '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', str(target)])
    return target


@pytest.mark.parametrize('text', ['', 'Hello {world} \\ नमस्ते 🎮'])
def test_portrait_render_format_audio_and_faststart(source, tmp_path, text):
    ass = tmp_path / 'overlay.ass'
    make_ass(ass, 'FORTNITE STREAM MOMENT', 1.2,
             [{'start': 0, 'end': 1.2, 'text': text}] if text else [])
    target = tmp_path / 'short.mp4'
    render_short(source, target, ass, 6, 1.2, 0)
    info = probe(target)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    audio = next(s for s in info['streams'] if s['codec_type'] == 'audio')
    assert (video['width'], video['height'], video['codec_name']) == (1080, 1920, 'h264')
    assert (video['r_frame_rate'], video['pix_fmt'], audio['codec_name']) == ('30/1', 'yuv420p', 'aac')
    assert 0 < float(info['format']['duration']) <= 1.45
    data = target.read_bytes()
    assert data.find(b'moov') < data.find(b'mdat')
    wav = tmp_path / 'mixed.wav'
    extract_audio(target, wav, 0)
    assert energy_per_second(wav).max() > .02
    assert not list(tmp_path.glob('*.partial.mp4'))


def test_cli_local_end_to_end_and_reuse(source, tmp_path):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / 'drafts'
    command = [sys.executable, str(root / 'clipper.py'), '--input', str(source),
               '--output', str(output), '--mic-track', '0', '--no-transcribe', '--max-shorts', '1']
    completed = subprocess.run(command, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    manifest = next(output.glob('*/manifest.json'))
    report = json.loads(manifest.read_text())
    assert report['status'] == 'review_required'
    assert len(report['shorts']) == 1
    short = report['shorts'][0]
    target = manifest.parent / short['path']
    assert short['end_seconds'] <= report['source']['duration_seconds']
    assert short['transcript'] == ''
    from edit_clip import edit_headline
    original = target.read_bytes()
    edit_headline(output, manifest.parent.name, short['path'], 'A custom headline')
    assert (manifest.parent / 'short_01.original.mp4').read_bytes() == original
    assert target.read_bytes() != original
    assert json.loads(manifest.read_text())['shorts'][0]['headline'] == 'A custom headline'
    before = target.stat().st_mtime_ns
    completed = subprocess.run(command, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert target.stat().st_mtime_ns == before
    assert 'reusing validated' in completed.stdout
    assert json.loads(manifest.read_text())['shorts'][0]['headline'] == 'A custom headline'


def test_real_probe_rejects_no_audio_and_corrupt_container(tmp_path):
    silent = tmp_path / 'no_audio.mp4'
    run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi',
         '-i', 'color=c=black:s=320x180:r=30', '-t', '1', '-c:v', 'libx264', str(silent)])
    with pytest.raises(ValueError, match='audio stream'):
        validate_media(silent)
    broken = tmp_path / 'broken.mp4'
    broken.write_bytes(b'not a video')
    with pytest.raises(RuntimeError, match='Command failed'):
        validate_media(broken)


def test_failed_render_preserves_existing_output(source, tmp_path):
    target = tmp_path / 'short.mp4'
    target.write_bytes(b'existing draft')
    ass = tmp_path / 'overlay.ass'
    make_ass(ass, 'Headline', 1, [])
    with pytest.raises((ValueError, RuntimeError)):
        render_short(source, target, ass, 100, 1, 0)
    assert target.read_bytes() == b'existing draft'
    assert not list(tmp_path.glob('*.partial.mp4'))


def test_instagram_copy_preserves_video_and_normalizes_audio(source, tmp_path):
    from types import SimpleNamespace
    from publish_uploads import instagram_asset
    from publishing import file_hash
    from media import validate_short
    ass = tmp_path / 'overlay.ass'
    make_ass(ass, 'Reviewed clip', 3, [])
    original = tmp_path / 'short.mp4'
    render_short(source, original, ass, 6, 3, 0)
    digest = file_hash(original)
    (tmp_path / 'publish_media').mkdir()
    publisher = SimpleNamespace(store=SimpleNamespace(directory=tmp_path))
    record = {'sha': digest, 'asset': str(original), 'duration': 3}
    target = instagram_asset(publisher, record)
    validate_short(target, 3)
    audio = json.loads(run(['ffprobe', '-v', 'error', '-select_streams', 'a:0',
                            '-show_entries', 'stream=sample_rate,channels,codec_name', '-of', 'json', str(target)]))['streams'][0]
    assert audio == {'codec_name': 'aac', 'sample_rate': '48000', 'channels': 2}
    def video_hash(path):
        return run(['ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:v:0', '-c:v', 'copy', '-f', 'hash', '-'])
    assert video_hash(original) == video_hash(target)
    assert file_hash(original) == digest
    assert target.read_bytes().find(b'moov') < target.read_bytes().find(b'mdat')
    assert instagram_asset(publisher, record) == target


def test_native_combat_scan_on_synthetic_video(tmp_path):
    cv2 = pytest.importorskip('cv2')
    pytest.importorskip('rapidocr_onnxruntime')
    import numpy as np
    from clipper import combat_events

    for count in [1,2]:
        frame = np.zeros((720,1280,3),dtype=np.uint8)
        cv2.putText(frame,str(count),(int(1280*.798)+7,int(720*.024)+19),
                    cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),1,cv2.LINE_AA)
        if count == 2:
            cv2.putText(frame,'ELIMINATED',(700,210),cv2.FONT_HERSHEY_SIMPLEX,.8,
                        (255,255,255),2,cv2.LINE_AA)
        cv2.imwrite(str(tmp_path/f'{count}.png'),frame)
    video = tmp_path/'combat.mkv'
    run(['ffmpeg','-v','error','-y','-loop','1','-t','4','-i',str(tmp_path/'1.png'),
         '-loop','1','-t','8','-i',str(tmp_path/'2.png'),
         '-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0[out]',
         '-map','[out]','-r','30','-c:v','libx264','-preset','ultrafast',
         '-pix_fmt','yuv420p',str(video)])
    events = combat_events(video,12.,cache_path=tmp_path/'scan.json')
    assert len(events)==1 and events[0].raw_score==1
    assert 'ELIMINATED' in events[0].evidence
