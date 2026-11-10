"""Simple OBS recording directory watcher; processes a recording after size stops changing."""
from __future__ import annotations

import argparse
import json
import time
import traceback
from pathlib import Path

from clipper import VIDEO_SUFFIXES, process


def main() -> None:
    p = argparse.ArgumentParser(description='Watch OBS recordings and render Fortnite Shorts')
    p.add_argument('--recordings', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--mic-track', type=int, default=1)
    p.add_argument('--mix-track', type=int, default=0)
    p.add_argument('--max-shorts', type=int, default=3)
    p.add_argument('--model', default='base')
    p.add_argument('--ocr', action='store_true')
    p.add_argument('--stable-seconds', type=int, default=90)
    p.add_argument('--poll-seconds', type=int, default=15)
    args = p.parse_args()
    root, output = args.recordings.resolve(), args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    db_file = output / '.processed_recordings.json'
    processed = json.loads(db_file.read_text(encoding='utf-8')) if db_file.exists() else {}
    observed: dict[str, tuple[int, float]] = {}
    print(f'Watching {root}. Press Ctrl+C to stop.', flush=True)
    while True:
        try:
            for video in sorted(root.iterdir()):
                if not video.is_file() or video.suffix.lower() not in VIDEO_SUFFIXES:
                    continue
                stat = video.stat()
                key = f'{video.resolve()}|{stat.st_size}|{stat.st_mtime_ns}'
                if key in processed:
                    continue
                path_key = str(video.resolve())
                old = observed.get(path_key)
                if old is None or old[0] != stat.st_size:
                    observed[path_key] = (stat.st_size, time.monotonic())
                    continue
                if (time.monotonic() - old[1] < args.stable_seconds or
                        time.time() - stat.st_mtime < args.stable_seconds):
                    continue
                try:
                    print(f'Processing completed recording {video}', flush=True)
                    process(video, output, mic_track=args.mic_track,
                            mix_track=args.mix_track, max_shorts=args.max_shorts,
                            model_name=args.model, use_ocr=args.ocr)
                    processed[key] = 'done'
                    db_file.write_text(json.dumps(processed, indent=2), encoding='utf-8')
                except Exception:
                    print(f'Processing failed for {video}; remove its failed database entry to retry', flush=True)
                    traceback.print_exc()
                    # Avoid retry storms; a persisted failed entry needs manual removal.
                    processed[key] = 'failed'
                    db_file.write_text(json.dumps(processed, indent=2), encoding='utf-8')
        except KeyboardInterrupt:
            print('Watcher stopped.')
            return
        time.sleep(max(1, args.poll_seconds))


if __name__ == '__main__':
    main()
