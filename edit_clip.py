"""Re-render one draft headline, using its original source and saved speech captions."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
import textwrap


def normalize_headline(text: str) -> str:
    if not isinstance(text, str) or any(ord(c) < 32 and c not in '\t\r\n' for c in text):
        raise ValueError('Enter plain headline text.')
    text = ' '.join(text.split())
    if len(text) > 72 or len(textwrap.wrap(text, width=24)) > 3:
        raise ValueError('Keep the headline within 72 characters and three short lines.')
    return text


def edit_headline(output: Path, run: str, name: str, text: str) -> None:
    from clipper import make_ass, render_short, save_report

    headline = normalize_headline(text)
    output = output.resolve()
    if not isinstance(run, str) or not re.fullmatch(r'[\w-]{1,100}', run) or run.startswith('_'):
        raise ValueError('Invalid run.')
    directory = (output / run).resolve()
    if directory.parent != output or not re.fullmatch(r'short_\d+\.mp4', name):
        raise ValueError('Invalid clip.')
    manifest = directory / 'manifest.json'
    if manifest.resolve().parent != directory:
        raise ValueError('Invalid manifest.')
    report = json.loads(manifest.read_text(encoding='utf-8'))
    clip = next((s for s in report['shorts'] if s.get('path') == name
                 and s.get('status') == 'review_required'), None)
    if clip is None:
        raise ValueError('Choose a completed clip.')
    target = (directory / name).resolve()
    backup = directory / (Path(name).stem + '.original.mp4')
    if target.parent != directory or backup.resolve().parent != directory or not target.is_file():
        raise ValueError('Invalid clip file.')
    source = Path(report['source']['path']).resolve()
    if not source.is_file():
        raise ValueError('The original replay is missing. Restore it before editing the headline.')
    start, end = float(clip['start_seconds']), float(clip['end_seconds'])
    track = report['config']['mix_track']
    if (not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end
            or type(track) is not int or track < 0):
        raise ValueError('Invalid source interval or audio track.')
    print(f'render: updating headline for {name}...', flush=True)
    if not backup.exists():
        staged = backup.with_suffix('.partial.mp4')
        try:
            shutil.copy2(target, staged)
            staged.replace(backup)
        finally:
            staged.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix='headline_') as temp:
        overlay = Path(temp) / 'overlay.ass'
        make_ass(overlay, headline, end - start, clip.get('captions', []))
        render_short(source, target, overlay, start, end - start, track)
    clip['headline'] = headline
    clip['title'] = (headline + ' #Fortnite #Shorts').strip()
    save_report(directory, report)
    print(f'done: {manifest}', flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run', required=True)
    parser.add_argument('--clip', required=True)
    parser.add_argument('--headline', required=True)
    args = parser.parse_args()
    try:
        edit_headline(args.output, args.run, args.clip, args.headline)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        parser.exit(1, f'Could not update headline: {exc}\n')


if __name__ == '__main__':
    main()
