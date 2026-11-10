"""Shared FFmpeg commands and media validation for local files and cached replays."""
from __future__ import annotations

import json
import logging
import math
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger('clipper')


class MissingToolError(RuntimeError):
    """A missing executable is an environment error, not evidence of corrupt media."""


def run(args: list[str], *, cwd: Path | None = None) -> str:
    logger.info('Command: %s', args)
    try:
        completed = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                                   encoding='utf-8', errors='replace')
    except FileNotFoundError as exc:
        raise MissingToolError(f'{args[0]} was not found. Install FFmpeg and FFprobe and add them to PATH.') from exc
    if completed.stderr:
        logger.info('%s', completed.stderr)
    if completed.returncode:
        err = (completed.stderr or completed.stdout)[-3500:]
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(args[:5])}\n{err}")
    return completed.stdout


def probe(path: Path) -> dict[str, Any]:
    try:
        return json.loads(run(['ffprobe', '-v', 'error', '-show_entries',
                               'format=duration:stream=index,codec_type,codec_name,width,height,r_frame_rate,pix_fmt',
                               '-of', 'json', str(path)]))
    except json.JSONDecodeError as exc:
        raise ValueError(f'FFprobe returned invalid metadata for {path}') from exc


def validate_media(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f'Media file is missing or empty: {path}')
    info = probe(path)
    try:
        duration = float(info['format']['duration'])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f'Media has no readable duration: {path}') from exc
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f'Media duration must be positive: {path}')
    types = {s.get('codec_type') for s in info.get('streams', [])}
    if not {'video', 'audio'} <= types:
        raise ValueError(f'Media must contain video and at least one audio stream: {path}')
    return info


def validate_short(path: Path, duration: float) -> None:
    info = validate_media(path)
    video = next(s for s in info['streams'] if s.get('codec_type') == 'video')
    audio = next(s for s in info['streams'] if s.get('codec_type') == 'audio')
    if ((video.get('width'), video.get('height')) != (1080, 1920)
            or video.get('codec_name') != 'h264' or audio.get('codec_name') != 'aac'
            or video.get('pix_fmt') != 'yuv420p' or video.get('r_frame_rate') != '30/1'
            or abs(float(info['format']['duration']) - duration) > .25):
        raise ValueError('Rendered Short failed format/duration validation.')
