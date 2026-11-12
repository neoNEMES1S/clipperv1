import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from clipper import combat_events
import clipper


def test_completed_combat_scan_reuses_cache_without_loading_ocr(tmp_path, monkeypatch):
    video = tmp_path / 'source.mkv'
    video.write_bytes(b'source')
    stat = video.stat()
    source = {'path':str(video.resolve()),'size':stat.st_size,'mtime_ns':stat.st_mtime_ns,
              'duration':120.,'detector_version':2,'sample_seconds':2}
    event = {'time':60.,'score':4.5,'source':'kill_counter_change','raw_score':1.,'evidence':'HUD 0 -> 1'}
    cache = tmp_path / 'scan.json'
    cache.write_text(json.dumps({'source':source,'events':[event]}))
    monkeypatch.setitem(sys.modules,'cv2',None)
    monkeypatch.setitem(sys.modules,'rapidocr_onnxruntime',None)
    events = combat_events(video,120.,cache_path=cache)
    assert len(events) == 1 and events[0].time == 60


def test_combat_scan_rejects_cache_for_another_source(tmp_path, monkeypatch):
    video = tmp_path / 'source.mkv'
    video.write_bytes(b'source')
    cache = tmp_path / 'scan.json'
    cache.write_text(json.dumps({'source':{'path':'different'},'events':[]}))
    monkeypatch.setitem(sys.modules,'rapidocr_onnxruntime',None)
    with pytest.raises(RuntimeError,match='requirements-combat.txt'):
        combat_events(video,120.,cache_path=cache)


@pytest.mark.parametrize('notice,expected',[('ELIMINATED opponent',1),('Loot collected',0)])
def test_scan_reads_hud_and_excludes_other_players_kill_feed(tmp_path, monkeypatch, notice, expected):
    video = tmp_path / 'source.mkv'
    video.write_bytes(b'source')
    frame = np.zeros((720,1280,3),dtype=np.uint8)
    frame[int(720*.024):int(720*.063),int(1280*.798):int(1280*.831)] = 127
    frame[360:450,20:350] = 255  # Other players' kill feed must never be the OCR input.
    cap = Mock()
    cap.isOpened.return_value = True
    cap.read.return_value = (True,frame)
    digits = iter(['0','0','1','1'])
    calls = []

    def recognize(crop, **kwargs):
        calls.append(crop)
        if len(calls)<=4:
            assert np.all(crop==127)
            return ([[next(digits),.99]],None)
        assert np.all(crop==0)
        return ([[[],notice,.95]],None)

    monkeypatch.setitem(sys.modules,'cv2',SimpleNamespace(
        VideoCapture=lambda p:cap, CAP_PROP_POS_MSEC=0, resize=lambda image,*a,**kw:image))
    monkeypatch.setattr(clipper,'hud_counter_image',lambda crop:crop)
    monkeypatch.setitem(sys.modules,'rapidocr_onnxruntime',SimpleNamespace(RapidOCR=lambda **kwargs:recognize))
    events = combat_events(video,8,cache_path=tmp_path/'scan.json')
    assert len(events)==expected
    if expected:
        assert events[0].time==4 and notice.upper() in events[0].evidence
    assert (tmp_path/'scan.json').is_file()
    cap.release.assert_called_once()


def test_scan_read_failure_releases_capture_and_does_not_cache(tmp_path, monkeypatch):
    video = tmp_path / 'source.mkv'
    video.write_bytes(b'source')
    cap = Mock()
    cap.isOpened.return_value = True
    cap.read.return_value = (False,None)
    monkeypatch.setitem(sys.modules,'cv2',SimpleNamespace(VideoCapture=lambda p:cap, CAP_PROP_POS_MSEC=0))
    monkeypatch.setitem(sys.modules,'rapidocr_onnxruntime',SimpleNamespace(RapidOCR=lambda **kw:Mock()))
    with pytest.raises(RuntimeError,match='could not read frame'):
        combat_events(video,8,cache_path=tmp_path/'scan.json')
    assert not (tmp_path/'scan.json').exists()
    cap.release.assert_called_once()


def test_native_counter_model_reads_numbers_and_rejects_blank_background():
    cv2 = pytest.importorskip('cv2')
    rapid = pytest.importorskip('rapidocr_onnxruntime')
    reader = rapid.RapidOCR(intra_op_num_threads=2,inter_op_num_threads=1)
    assert clipper.hud_counter_image(np.zeros((27,42,3),dtype=np.uint8)) is None
    assert clipper.hud_counter_image(np.full((27,42,3),255,dtype=np.uint8)) is None
    for text in ['1','2','12']:
        crop = np.full((27,42,3),30,dtype=np.uint8)
        cv2.putText(crop,text,(7,19),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),1,cv2.LINE_AA)
        image = clipper.hud_counter_image(crop)
        result,_ = reader(image,use_det=False,use_cls=False)
        assert result[0][0]==text and result[0][1]>.8
