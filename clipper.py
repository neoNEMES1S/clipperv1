"""Local, post-stream Fortnite highlight clipper.

MVP signal quality: microphone excitement + optional OCR text; not gameplay understanding.
Requires ffmpeg + ffprobe available on PATH. Safe-by-default: creates drafts only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import re
import tempfile
import textwrap
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from media import logger, probe, run, validate_media, validate_short

VIDEO_SUFFIXES = {'.mkv', '.mp4', '.mov', '.ts', '.webm'}
# Ranking weights: OCR is secondary; independent audio + HUD evidence earns a bonus.
SIGNAL_WEIGHTS = {'mic_reaction': 1.0, 'victory_ocr': .9, 'elimination_ocr': .75,
                  'kill_counter_change': 1.2}
MULTISIGNAL_BONUS = .3
PIPELINE_VERSION = '1.4'


@dataclass
class Event:
    time: float
    score: float
    source: str
    raw_score: float | None = None
    evidence: str | None = None

    def metadata(self) -> dict[str, Any]:
        normalized = (self.score / (1 + self.score) if self.source == 'mic_reaction'
                      else self.score / 5.5)
        return {'time_seconds': self.time, 'signal_type': self.source,
                'raw_score': self.score if self.raw_score is None else self.raw_score,
                'normalized_score': round(min(1., max(0., normalized)), 6),
                'evidence': self.evidence}


@dataclass
class Clip:
    start: float
    end: float
    score: float
    signals: list[str]
    anchor: float


def audio_count(info: dict[str, Any]) -> int:
    return sum(1 for stream in info['streams'] if stream.get('codec_type') == 'audio')


def extract_audio(video: Path, dest: Path, track: int, start: float | None = None,
                  length: float | None = None) -> None:
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y']
    if start is not None:
        cmd += ['-ss', str(round(start, 3))]
    cmd += ['-i', str(video)]
    if length is not None:
        cmd += ['-t', str(round(length, 3))]
    cmd += ['-map', f'0:a:{track}', '-vn', '-ac', '1', '-ar', '16000',
            '-c:a', 'pcm_s16le', str(dest)]
    run(cmd)


def energy_per_second(wav_path: Path) -> np.ndarray:
    """Stream a WAV one second at a time instead of loading hours of audio in RAM."""
    levels: list[float] = []
    with wave.open(str(wav_path), 'rb') as f:
        if f.getnchannels() != 1 or f.getsampwidth() != 2:
            raise ValueError('Expected mono 16-bit PCM WAV')
        rate = f.getframerate()
        while True:
            frames = f.readframes(rate)
            if not frames:
                break
            samples = np.frombuffer(frames, dtype='<i2').astype(np.float32) / 32768.0
            levels.append(float(np.sqrt(np.mean(samples * samples))))
    return np.asarray(levels, dtype=np.float32)


def microphone_events(levels: np.ndarray, limit: int = 80, *, peak_ratio: float = 1.4,
                      min_spacing: float = 14) -> list[Event]:
    if peak_ratio <= 1 or min_spacing < 0:
        raise ValueError('Peak ratio must exceed 1 and spacing must be nonnegative.')
    if levels.size == 0 or limit <= 0:
        return []
    levels = np.nan_to_num(levels, nan=0., posinf=0., neginf=0.)
    baseline = max(.006, float(np.median(levels)))
    threshold = max(0.012, float(np.percentile(levels, 75)), baseline * peak_ratio)
    events = []
    for i in range(len(levels)):
        value = float(levels[i])
        if value < threshold:
            continue
        if value < float(np.max(levels[max(i - 5, 0):min(i + 6, len(levels))])):
            continue
        local_floor = max(.006, float(np.median(levels[max(i - 15, 0):min(i + 16, len(levels))])))
        if value < local_floor * peak_ratio:
            continue
        score = value / max(baseline, 0.008)
        events.append(Event(float(i), score, 'mic_reaction', value,
                            f'RMS={value:.4f}; recording floor={baseline:.4f}; local floor={local_floor:.4f}'))
    chosen: list[Event] = []
    for candidate in sorted(events, key=lambda e: e.score, reverse=True):
        if all(abs(candidate.time - found.time) >= min_spacing for found in chosen):
            chosen.append(candidate)
        if len(chosen) >= limit:
            break
    return sorted(chosen, key=lambda e: e.time)


def ocr_events(video: Path, duration: float, sample_seconds: int = 8) -> list[Event]:
    """Optional expensive scan. Requires OpenCV, pytesseract and Tesseract binary."""
    try:
        import cv2
        import pytesseract
    except ImportError as e:
        raise RuntimeError('Enable OCR with: pip install opencv-python-headless pytesseract') from e
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f'Cannot decode video for OCR: {video}')
    results = []
    try:
        for sec in range(2, max(3, int(duration)), sample_seconds):
            cap.set(cv2.CAP_PROP_POS_MSEC, sec * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            height, width = frame.shape[:2]
            roi = frame[int(height * .07):int(height * .93), int(width * .05):int(width * .95)]
            resized = cv2.resize(roi, (960, int(960 * roi.shape[0] / roi.shape[1])))
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            try:
                text = pytesseract.image_to_string(gray, config='--psm 11').upper()
            except pytesseract.TesseractNotFoundError as e:
                raise RuntimeError('Tesseract binary is not installed or not on PATH') from e
            compact = re.sub(r'\s+', ' ', text)
            if 'VICTORY ROYALE' in compact or 'VICTORYROYALE' in compact:
                results.append(Event(float(sec), 5.5, 'victory_ocr', 1., compact[:300]))
            elif 'ELIMINATED' in compact or 'ELIMINATION' in compact:
                results.append(Event(float(sec), 4.5, 'elimination_ocr', 1., compact[:300]))
    finally:
        cap.release()
    return results


def kill_counter_events(readings: list[dict[str, Any]]) -> list[Event]:
    """Require two agreeing HUD reads; existing counts and match resets are not kills."""
    events = []
    stable = pending = None
    first_time = 0.
    last_seen = None
    for reading in readings:
        count = reading['count']
        if count is None or not 0 <= count <= 99 or reading['confidence'] < .8:
            pending = None
            continue
        if last_seen is None or reading['time'] - last_seen > 12:
            stable = pending = None
        last_seen = reading['time']
        if count != pending:
            pending, first_time = count, reading['time']
            continue
        if stable is not None and 0 < count - stable <= 4:
            delta = count - stable
            events.append(Event(first_time, 4 + .5 * delta, 'kill_counter_change', float(delta),
                                f'Personal HUD count {stable} -> {count}; two agreeing reads; '
                                f'OCR confidence={reading["confidence"]:.3f}'))
        stable = count
    return events


def hud_counter_image(crop: np.ndarray) -> np.ndarray | None:
    """Isolate white HUD digits from changing scenery before recognizing a short number."""
    import cv2
    mask = cv2.inRange(crop, np.array([180,180,180],dtype=np.uint8),
                       np.array([255,255,255],dtype=np.uint8))
    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    digits = np.zeros_like(mask)
    for label, (x,y,width,height,area) in enumerate(stats[1:],1):
        if (x > 0 and y > 0 and x+width < mask.shape[1] and y+height < mask.shape[0]
                and height >= 3 and width >= 2 and area >= 8):
            digits[labels == label] = 255
    points = cv2.findNonZero(digits)
    if points is None:
        return None
    x,y,width,height = cv2.boundingRect(points)
    digits = cv2.copyMakeBorder(digits[y:y+height,x:x+width],4,4,4,4,cv2.BORDER_CONSTANT,value=0)
    return cv2.resize(digits,None,fx=4,fy=4)


def combat_events(video: Path, duration: float, *, cache_path: Path,
                  progress: Any = print) -> list[Event]:
    """Read the personal elimination counter, outside the other players' kill feed."""
    stat = video.stat()
    identity = {'path': str(video.resolve()), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
                'duration': duration, 'detector_version': 2, 'sample_seconds': 2}
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding='utf-8'))
            if cached['source'] == identity:
                events = [Event(**e) for e in cached['events']]
                progress(f'combat: reusing {len(events)} cached visual events')
                return events
        except (OSError, KeyError, TypeError, ValueError):
            logger.warning('Ignoring invalid combat scan cache: %s', cache_path)
    try:
        import cv2
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise RuntimeError('Combat selection requires local OCR: pip install -r requirements-combat.txt') from exc
    reader = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f'Cannot decode gameplay HUD: {video}')
    readings = []
    try:
        for second in range(0, int(duration), 2):
            cap.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError(f'Combat scan could not read frame at {second}s; source retained for retry.')
            height, width = frame.shape[:2]
            # shortcut: standard Fortnite HUD position; calibrate this region for custom HUD layouts.
            crop = frame[int(height * .024):int(height * .063),
                         int(width * .798):int(width * .831)]
            count, confidence = None, 0.
            for image in (hud_counter_image(crop), cv2.resize(crop,None,fx=4,fy=4)):
                if image is None:
                    continue
                result, _ = reader(image, use_det=False, use_cls=False)
                digits = [(int(text.strip().strip('.,，。')),float(conf)) for text,conf in (result or [])
                          if re.fullmatch(r'[0-9]{1,2}',text.strip().strip('.,，。'))]
                if len(digits) == 1 and digits[0][1] > confidence:
                    count, confidence = digits[0]
                if confidence >= .8:
                    break
            readings.append({'time': float(second), 'count': count, 'confidence': confidence})
            if second % 600 == 0:
                progress(f'combat: scanned {second / 60:.0f}/{duration / 60:.0f} minutes of personal HUD')
        potential = kill_counter_events(readings)
        events = []
        for event in potential:
            for offset in (-4, -2, 0, 1):
                when = max(0., event.time + offset)
                cap.set(cv2.CAP_PROP_POS_MSEC, when * 1000)
                ok, frame = cap.read()
                if not ok:
                    continue
                height, width = frame.shape[:2]
                confirmed = False
                for top,bottom in ((.15,.45),(.68,.86)):
                    crop = frame[int(height*top):int(height*bottom), int(width*.35):int(width*.85)]
                    result, _ = reader(cv2.resize(crop,None,fx=2,fy=2), use_cls=False)
                    text = ' '.join(s for _, s, conf in (result or []) if conf >= .65).upper()
                    # Compression can blur the suffix; the counter change and cropped location are also required.
                    if re.search(r'\bELIMIN[A-Z]{2,10}\b|\bKNOCKED\s*DOWN', text):
                        event.evidence += f'; center HUD at {when:.1f}s: {text[:250]}'
                        event.score += .5
                        events.append(event)
                        confirmed = True
                        break
                if confirmed:
                    break
        payload = {'source': identity, 'readings': readings, 'events': [asdict(e) for e in events]}
        temporary = cache_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        temporary.replace(cache_path)
        progress(f'combat: {len(events)}/{len(potential)} HUD counter increases have a center elimination/knockdown notice')
        return events
    finally:
        cap.release()


def select_clips(events: list[Event], duration: float, maximum: int, *,
                 pre_roll: float = 23, post_roll: float = 13, min_length: float = 8,
                 combat_only: bool = False) -> list[Clip]:
    if maximum <= 0 or duration <= 0:
        return []
    if pre_roll < 0 or post_roll < 0 or min_length <= 0 or pre_roll + post_roll < min_length:
        raise ValueError('Clip rolls must be nonnegative and total at least the positive minimum length.')
    events = [e for e in events if math.isfinite(e.time) and 0 <= e.time <= duration
              and math.isfinite(e.score) and e.score > 0]
    candidates: list[Clip] = []
    for e in events:
        if combat_only and e.source != 'kill_counter_change':
            continue
        start, end = max(0.0, e.time - pre_roll), min(duration, e.time + post_roll)
        start, end = math.ceil(start * 1000) / 1000, math.floor(end * 1000) / 1000
        if end - start < min_length:
            continue
        nearby = [s for s in events if start <= s.time <= end and abs(s.time - e.time) <= 10]
        if not nearby:
            continue
        sources = sorted({s.source for s in nearby})
        strengths = [max(s.metadata()['normalized_score'] for s in nearby if s.source == source)
                     * SIGNAL_WEIGHTS.get(source, 1.)
                     * (.15 if combat_only and source == 'mic_reaction' else 1.) for source in sources]
        score = sum(strengths) + MULTISIGNAL_BONUS * max(0, len(sources) - 1) * (.15 if combat_only else 1.)
        if combat_only:
            kills = sum(s.raw_score or 1 for s in nearby if s.source == 'kill_counter_change')
            score += .25 * min(3, max(0, kills - 1))
        candidates.append(Clip(round(start, 3), round(end, 3),
                               round(score, 6), sources, e.time))
    chosen: list[Clip] = []
    for c in sorted(candidates, key=lambda c: (-c.score, c.start, c.anchor)):
        overlap = [max(0, min(c.end, k.end) - max(c.start, k.start)) for k in chosen]
        if all(seconds <= 4 for seconds in overlap):
            chosen.append(c)
        if len(chosen) >= maximum:
            break
    return sorted(chosen, key=lambda c: c.start)


def whisper_segments(audio_path: Path, model: Any) -> list[dict[str, Any]]:
    with wave.open(str(audio_path), 'rb') as audio:
        duration = math.floor(audio.getnframes() / audio.getframerate() * 100) / 100
    segments, _ = model.transcribe(str(audio_path), vad_filter=True, beam_size=1,
                                   condition_on_previous_text=False, temperature=0)
    result = []
    previous_end = 0.
    for segment in segments:
        if segment.avg_logprob < -1 or segment.compression_ratio > 2.4 or segment.no_speech_prob > .6:
            logger.warning('Omitting unreliable Whisper segment: logprob=%.3f, compression=%.3f, no_speech=%.3f',
                           segment.avg_logprob, segment.compression_ratio, segment.no_speech_prob)
            continue
        start, end = float(segment.start), float(segment.end)
        if not math.isfinite(start) or not math.isfinite(end):
            continue
        start, end = round(max(previous_end, 0., start), 2), round(min(duration, end), 2)
        if not segment.text.strip() or end <= start:
            continue
        result.append({'start': start, 'end': end, 'text': segment.text.strip()})
        previous_end = end
    return result


def caption_chunks(segments: list[dict[str, Any]], words_per_caption: int = 5) -> list[dict[str, Any]]:
    if words_per_caption <= 0:
        raise ValueError('Words per caption must be positive.')
    chunks = []
    previous_end = 0.
    for segment in segments:
        words = segment['text'].split()
        if not words:
            continue
        start, end = float(segment['start']), float(segment['end'])
        if not math.isfinite(start) or not math.isfinite(end):
            continue
        start = max(previous_end, 0., start)
        if end <= start:
            continue
        length = end - start
        groups = []
        for i in range(0, len(words), words_per_caption):
            groups.extend(textwrap.wrap(' '.join(words[i:i + words_per_caption]), width=32,
                                        break_on_hyphens=False))
        count = len(groups)
        for i in range(count):
            a = start + length * (i / count)
            b = start + length * ((i + 1) / count)
            if round(b, 2) > round(a, 2):
                chunks.append({'start': round(a, 2), 'end': round(b, 2), 'text': groups[i]})
        previous_end = end
    return chunks


def ass_time(seconds: float) -> str:
    centis = max(0, round(seconds * 100))
    return f'{centis // 360000}:{(centis // 6000) % 60:02}:{(centis // 100) % 60:02}.{centis % 100:02}'


def escape_ass(text: str) -> str:
    # A word joiner prevents ASS control sequences without adding a visible second slash.
    return (text.replace('\\', '\\\u2060').replace('{', r'\{').replace('}', r'\}')
            .replace('\r\n', '\n').replace('\r', '\n').replace('\n', r'\N'))


def hook_for(signals: list[str], transcript: str) -> str:
    if 'victory_ocr' in signals:
        return 'POSSIBLE VICTORY MOMENT'
    if 'elimination_ocr' in signals or 'kill_counter_change' in signals:
        return 'POSSIBLE ELIMINATION MOMENT'
    return 'FORTNITE STREAM MOMENT'


def make_ass(path: Path, title: str, duration: float, chunks: list[dict[str, Any]]) -> None:
    # shortcut: system fonts determine Hindi/emoji coverage; bundle fonts when consistent glyphs are needed.
    header = '''[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,Arial,71,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,4,2,8,70,70,240,1
Style: Caption,Arial,62,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,4,1,2,70,70,440,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    headline = r'\N'.join(escape_ass(line) for line in textwrap.wrap(title, width=24))
    lines = [header, f'Dialogue: 0,{ass_time(0)},{ass_time(duration)},Hook,,0,0,0,,{headline}']
    previous_end = 0.
    for c in chunks:
        start, end = float(c['start']), float(c['end'])
        if not math.isfinite(start) or not math.isfinite(end):
            continue
        start, end = max(previous_end, 0., start), min(duration, end)
        if round(end * 100) <= round(start * 100):
            continue
        lines.append(f"Dialogue: 1,{ass_time(start)},{ass_time(end)},Caption,,0,0,0,,{escape_ass(c['text'])}")
        previous_end = end
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def render_short(video: Path, target: Path, overlay_ass: Path,
                 start: float, duration: float, audio_track: int) -> None:
    video, overlay_ass = video.resolve(), overlay_ass.resolve()
    target = target.resolve()
    partial = target.with_suffix('.partial.mp4')
    graph = ('[0:v:0]split=2[bgsrc][fgsrc];'
             '[bgsrc]scale=1080:1920:force_original_aspect_ratio=increase,'
             'crop=1080:1920,setsar=1,boxblur=20:2[bg];'
             '[fgsrc]scale=1080:720:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1[fg];'
             '[bg][fg]overlay=(W-w)/2:(H-h)/2,'
             'subtitles=overlay.ass:original_size=1080x1920,'
             'fps=30,format=yuv420p[outv]')
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
           '-ss', str(round(start, 3)), '-i', str(video), '-t', str(round(duration, 3)),
           '-filter_complex', graph, '-map', '[outv]', '-map', f'0:a:{audio_track}',
           '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
           '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart',
           '-pix_fmt', 'yuv420p', str(partial)]
    try:
        run(cmd, cwd=overlay_ass.parent)
        validate_short(partial, duration)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


def validate_options(mic_track: int, mix_track: int, max_shorts: int,
                     pre_roll: float, post_roll: float, min_clip_seconds: float,
                     peak_ratio: float, peak_spacing: float) -> None:
    if mic_track < 0 or mix_track < 0 or max_shorts < 0:
        raise ValueError('Audio track indices and --max-shorts must be nonnegative.')
    if not all(math.isfinite(x) for x in (pre_roll, post_roll, min_clip_seconds, peak_ratio, peak_spacing)):
        raise ValueError('Detection parameters must be finite numbers.')
    if pre_roll < 0 or post_roll < 0 or min_clip_seconds <= 0 or pre_roll + post_roll < min_clip_seconds:
        raise ValueError('Pre/post-roll must be nonnegative and total at least --min-clip-seconds (> 0).')
    if peak_ratio <= 1 or peak_spacing < 0:
        raise ValueError('--peak-ratio must exceed 1 and --peak-spacing must be nonnegative.')


def save_report(destination: Path, report: dict[str, Any]) -> None:
    temporary = destination / 'manifest.json.tmp'
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    temporary.replace(destination / 'manifest.json')
    notes = ['# Draft Shorts — human review required', '', f"Job status: {report['status']}", '',
             'Review gameplay, audio, captions, OCR evidence and titles before uploading. Nothing was published.', '']
    if report.get('error'):
        notes.extend([f"Error: {report['error']}", ''])
    if not report['shorts']:
        notes.extend(['No rendered drafts. See candidates in manifest.json for analysis results.', ''])
    for short in report['shorts']:
        notes.extend([f"## {short['id']} ({short['status']})", '',
                      f"File: {short['path']}", '', f"Title: {short['title']}", '',
                      short['description'], '',
                      f"Source: {short['start_seconds']:.2f}s to {short['end_seconds']:.2f}s", '',
                      f"Transcript: {short['transcript'] or '(no speech transcribed)'}", ''])
    (destination / 'posting_notes.md').write_text('\n'.join(notes), encoding='utf-8')


def process(video: Path, output: Path, mic_track: int = 1, mix_track: int = 0,
            max_shorts: int = 3, model_name: str = 'base', use_ocr: bool = False,
            no_transcribe: bool = False, dry_run: bool = False,
            source_url: str | None = None, *, pre_roll: float = 23, post_roll: float = 13,
            min_clip_seconds: float = 8, peak_ratio: float = 1.4,
            peak_spacing: float = 14, combat_only: bool = False) -> dict[str, Any]:
    validate_options(mic_track, mix_track, max_shorts, pre_roll, post_roll,
                     min_clip_seconds, peak_ratio, peak_spacing)
    video, output = video.resolve(), output.resolve()
    if not video.is_file():
        raise FileNotFoundError(f'Input recording does not exist: {video}')
    if video.suffix.lower() not in VIDEO_SUFFIXES:
        raise ValueError(f'Unsupported input type: {video.suffix}')
    from youtube_source import youtube_video_id
    video_id = youtube_video_id(source_url) if source_url else None
    config = {'pipeline_version': PIPELINE_VERSION, 'max_shorts': max_shorts,
              'whisper_model': model_name, 'ocr_enabled': use_ocr,
              'no_transcribe': no_transcribe, 'dry_run': dry_run,
              'combat_only': combat_only,
              'mic_track': mic_track, 'mix_track': mix_track,
              'pre_roll': pre_roll, 'post_roll': post_roll, 'min_clip_seconds': min_clip_seconds,
              'peak_ratio': peak_ratio, 'peak_spacing': peak_spacing,
              'signal_weights': SIGNAL_WEIGHTS, 'multisignal_bonus': MULTISIGNAL_BONUS}
    stat = video.stat()
    identity = f'{video}|{stat.st_size}|{stat.st_mtime_ns}|{json.dumps(config, sort_keys=True)}'
    signature = hashlib.sha256(identity.encode()).hexdigest()[:12]
    safe_name = re.sub(r'[^\w-]', '_', video_id or video.stem)[:60]
    destination = output / f'{safe_name}_{signature}'
    destination.mkdir(parents=True, exist_ok=True)
    previous = {}
    manifest = destination / 'manifest.json'
    if manifest.exists():
        try:
            previous = json.loads(manifest.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            pass
    if not isinstance(previous, dict) or not isinstance(previous.get('shorts', []), list):
        previous = {}
    report: dict[str, Any] = {
        'schema_version': '1.0', 'status': 'created', 'config': config,
        'source': {'type': 'youtube' if source_url else 'local', 'url': source_url,
                   'video_id': video_id, 'path': str(video),
                   'downloaded_source_path': str(video) if source_url else None},
        'source_url': source_url, 'output_directory': str(destination),
        'shorts': [], 'candidates': [], 'events': [], 'warnings': [],
    }
    report['shorts'] = [s.copy() for s in previous.get('shorts', []) if isinstance(s, dict)]
    handler = logging.FileHandler(destination / 'processing.log', encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    def progress(message: str) -> None:
        print(message, flush=True)
        logger.info(message)

    try:
        save_report(destination, report)
        progress('validate: inspecting video and audio streams...')
        info = validate_media(video)
        duration = float(info['format']['duration'])
        report['source']['duration_seconds'] = report['duration_seconds'] = duration
        n_audio = report['audio_tracks'] = audio_count(info)
        if n_audio <= max(mic_track, mix_track):
            raise ValueError(f'Recording has {n_audio} audio track(s); mic index={mic_track}, mix index={mix_track}. '
                             'For mixed audio use --mic-track 0; local OBS defaults to mic index 1.')
        with tempfile.TemporaryDirectory(prefix='fortnite_clipper_') as temp:
            work = Path(temp)
            progress('analyze: scanning audio energy in one-second chunks...')
            mic_wav = work / 'analysis.wav'
            extract_audio(video, mic_wav, mic_track)
            events = microphone_events(energy_per_second(mic_wav), peak_ratio=peak_ratio,
                                       min_spacing=peak_spacing)
            mic_wav.unlink()  # Free the full-length PCM file before rendering.
            if combat_only:
                progress('analyze: scanning personal elimination counter (combat-only)...')
                scan_root = output / '_combat_scans'
                scan_root.mkdir(exist_ok=True)
                source_key = hashlib.sha256(f'{video}|{stat.st_size}|{stat.st_mtime_ns}'.encode()).hexdigest()[:12]
                events += combat_events(video, duration, cache_path=scan_root / f'{source_key}.json',
                                        progress=progress)
            if use_ocr:
                progress('analyze: scanning optional HUD OCR...')
                try:
                    events += ocr_events(video, duration)
                except Exception as exc:
                    warning = f'Optional OCR failed; continuing with audio only: {exc}'
                    report['warnings'].append(warning)
                    progress(f'Warning: {warning}')
                    logger.exception('OCR failed')
            clips = select_clips(events, duration, max_shorts, pre_roll=pre_roll,
                                 post_roll=post_roll, min_length=min_clip_seconds, combat_only=combat_only)
            report['events'] = [e.metadata() for e in events]
            report['candidates'] = [dict(asdict(c), start_seconds=c.start, end_seconds=c.end,
                                        evidence=[e.metadata() for e in events
                                                  if c.start <= e.time <= c.end and abs(e.time - c.anchor) <= 10])
                                    for c in clips]
            progress(f'select: {len(events)} events; {len(clips)} distinct candidate(s).')
            if not clips:
                progress('No convincing candidates; no Shorts will be invented.')
            report['shorts'] = []
            save_report(destination, report)
            model = None
            for i, clip in enumerate(clips, 1):
                if dry_run:
                    break
                name = f'short_{i:02}'
                title = hook_for(clip.signals, '')
                meta = {'id': name, 'filename': f'{name}.mp4', 'path': f'{name}.mp4',
                        'title': f'{title} #Fortnite #Shorts',
                        'description': 'Candidate moment from a Fortnite stream. Review before posting.\n#Fortnite #Shorts #Gaming',
                        'start_seconds': clip.start, 'end_seconds': clip.end, 'score': clip.score,
                        'signals': clip.signals, 'transcript': '', 'captions': [], 'status': 'created'}
                report['shorts'].append(meta)
                prior = next((s for s in previous.get('shorts', [])
                              if isinstance(s, dict) and s.get('id') == name), None)
                if (prior and prior.get('status') == 'review_required'
                        and prior.get('start_seconds') == clip.start and prior.get('end_seconds') == clip.end):
                    try:
                        validate_short(destination / meta['path'], clip.end - clip.start)
                    except (ValueError, RuntimeError):
                        pass
                    else:
                        for key in ('title', 'description', 'transcript', 'captions'):
                            meta[key] = prior.get(key, meta[key])
                        meta['status'] = 'review_required'
                        report['warnings'].extend(w for w in previous.get('warnings', [])
                                                  if isinstance(w, str) and w.startswith(f'{name}:'))
                        progress(f'render: reusing validated {name}.mp4')
                        save_report(destination, report)
                        continue
                if not no_transcribe:
                    progress(f'transcribe: {name}, local Whisper {model_name}...')
                    if model is None:
                        try:
                            from faster_whisper import WhisperModel
                        except ImportError as exc:
                            raise RuntimeError('Could not load faster-whisper. Install requirements.txt; on Windows, '
                                               'also install the Microsoft Visual C++ x64 runtime. '
                                               f'Details: {exc}') from exc
                        model = WhisperModel(model_name, device='cpu', compute_type='int8')
                    speech_wav = work / f'{name}.wav'
                    extract_audio(video, speech_wav, mic_track, clip.start, clip.end - clip.start)
                    segments = whisper_segments(speech_wav, model)
                    if not segments:
                        warning = f'{name}: no reliable speech transcript; captions omitted. Review the source audio/model choice.'
                        report['warnings'].append(warning)
                        progress(f'Warning: {warning}')
                    meta['transcript'] = ' '.join(s['text'] for s in segments)
                    meta['captions'] = caption_chunks(segments)
                    speech_wav.unlink()
                else:
                    progress(f'transcribe: skipped for {name} (--no-transcribe).')
                save_report(destination, report)
                render_dir = work / name
                render_dir.mkdir()
                ass = render_dir / 'overlay.ass'
                make_ass(ass, title, clip.end - clip.start, meta['captions'])
                progress(f'render: {name}.mp4...')
                render_short(video, destination / meta['path'], ass,
                             clip.start, clip.end - clip.start, mix_track)
                meta['status'] = 'review_required'
                save_report(destination, report)
        report['status'] = 'review_required' if report['shorts'] else 'created'
        save_report(destination, report)
        progress(f'done: {manifest}')
        return report
    except (Exception, KeyboardInterrupt) as exc:
        report['status'], report['error'] = 'failed', str(exc) or type(exc).__name__
        for short in report['shorts']:
            if short['status'] == 'created':
                short['status'], short['error'] = 'failed', str(exc)
        logger.exception('Processing failed; source retained')
        try:
            save_report(destination, report)
        except OSError:
            logger.exception('Could not write failure metadata; check free space and permissions')
        raise
    finally:
        logger.removeHandler(handler)
        handler.close()


def main() -> None:
    parser = argparse.ArgumentParser(description='Create vertical Shorts from a completed YouTube livestream or OBS recording')
    parser.add_argument('--input', type=str, required=True, help='Local recording path OR ended YouTube livestream replay URL')
    parser.add_argument('--output', type=Path, required=True, help='Directory for generated Shorts')
    parser.add_argument('--mic-track', type=int, default=None, help='Zero-based audio stream index; default=1 for OBS, 0 for YouTube combined audio')
    parser.add_argument('--mix-track', type=int, default=0, help='Zero-based mixed audio stream index; OBS Track 1 = 0')
    parser.add_argument('--max-shorts', type=int, default=3, help='Maximum draft count; may return fewer or zero (default: 3)')
    parser.add_argument('--model', default='base', help='Whisper model name (base/small) or local CTranslate2 model directory')
    parser.add_argument('--ocr', action='store_true', help='Enable optional Fortnite HUD OCR')
    parser.add_argument('--combat-only', action='store_true',
                        help='Require personal HUD elimination-counter evidence; needs requirements-combat.txt')
    parser.add_argument('--no-transcribe', action='store_true', help='Disable speech transcription/captions; retain headline (testing only)')
    parser.add_argument('--dry-run', action='store_true', help='Analyze candidates without Whisper/MP4s; URL inputs still download the replay')
    parser.add_argument('--delete-download', action='store_true', help='Delete cached source after a successful render job; ignored for --dry-run')
    parser.add_argument('--pre-roll', type=float, default=23, help='Seconds before each event (default: 23)')
    parser.add_argument('--post-roll', type=float, default=13, help='Seconds after each event (default: 13)')
    parser.add_argument('--min-clip-seconds', type=float, default=8, help='Reject shorter windows (default: 8)')
    parser.add_argument('--peak-ratio', type=float, default=1.4, help='Minimum energy/floor ratio, greater than 1 (default: 1.4)')
    parser.add_argument('--peak-spacing', type=float, default=14, help='Minimum seconds between audio peaks (default: 14)')
    args = parser.parse_args()
    from youtube_source import download_youtube_video, is_web_url, youtube_video_id
    try:
        validate_options(0 if args.mic_track is None else args.mic_track, args.mix_track,
                         args.max_shorts, args.pre_roll, args.post_roll, args.min_clip_seconds,
                         args.peak_ratio, args.peak_spacing)
        if not args.model.strip():
            raise ValueError('--model must not be empty.')
        if is_web_url(args.input):
            youtube_video_id(args.input)
    except ValueError as exc:
        parser.error(str(exc))
    args.output = args.output.expanduser()
    try:
        args.output.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(args.output / 'clipper.log', encoding='utf-8')
    except OSError as exc:
        parser.exit(1, f'Cannot write output directory {args.output}; check free disk space and permissions: {exc}\n')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        source_url = args.input if is_web_url(args.input) else None
        if source_url:
            local_input = download_youtube_video(source_url, args.output / '_youtube_downloads')
            mic_track = 0 if args.mic_track is None else args.mic_track
            if mic_track != 0:
                print('Warning: YouTube replays use mixed audio; usually --mic-track 0.')
        else:
            local_input = Path(args.input).expanduser()
            mic_track = 1 if args.mic_track is None else args.mic_track
        process(local_input, args.output, mic_track, args.mix_track,
                args.max_shorts, args.model, args.ocr, args.no_transcribe, args.dry_run,
                source_url=source_url, pre_roll=args.pre_roll, post_roll=args.post_roll,
                min_clip_seconds=args.min_clip_seconds, peak_ratio=args.peak_ratio,
                peak_spacing=args.peak_spacing, combat_only=args.combat_only)
        if source_url and args.delete_download and not args.dry_run:
            local_input.unlink()
            print(f'Deleted downloaded video: {local_input}')
    except KeyboardInterrupt:
        logger.warning('Interrupted; source and partial downloads retained for retry')
        parser.exit(130, 'Interrupted. Source and partial downloads were retained; rerun the same command to resume.\n')
    except (OSError, ValueError, RuntimeError) as exc:
        logger.exception('Job failed')
        parser.exit(1, f'Error: {exc}\nSee {args.output / "clipper.log"} and any job processing.log.\n')
    finally:
        logger.removeHandler(handler)
        handler.close()


if __name__ == '__main__':
    main()
