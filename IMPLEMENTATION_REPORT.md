# Implementation and release validation

The core implementation and macOS/local release checks are complete. The authorized private repository is https://github.com/neoNEMES1S/clipperv1. Windows CI is prepared and is the remaining execution check at the time of this snapshot. Nothing uploads or publishes videos.

## Implemented

- A: strict single-video URL/ID validation, completed-replay checks, validated stable-ID cache, staged/resumable downloads, atomic cache promotion and actionable errors.
- B: bounded-memory energy scanning, recording/local prominence, normalized explainable events, weighted multi-signal ranking, clamped/deduplicated windows and analysis-only dry runs.
- C: selected-clip local Whisper, safe Unicode/ASS formatting and clip-relative captions, complete gameplay frame over blur, 1080×1920 H.264/AAC/30fps/yuv420p/faststart output, validated atomic renders.
- D: versioned/configuration-specific jobs, manifests/notes/logs, honest draft titles, failed/review-required statuses and validated clip reuse.
- E: offline unit tests, real FFmpeg and Whisper checks, actual replay processing, interrupted-download resume, URL failures and a prepared native Windows workflow.

Changed files: `clipper.py`, `youtube_source.py`, new shared `media.py`, a corrected watcher retry diagnostic in `watch.py`, runtime/development requirements, README, tests, `.gitignore`, and `.github/workflows/windows-tests.yml`. Existing CLI flags and OBS track defaults remain. Source metadata is now structured; dry runs do not imply MP4s exist.

## Automated verification

Original baseline: 8 tests passed (plus 9 unittest subtests).

Final local suite: **60 passed, plus 22 unittest subtests, with no skips**, including opt-in real Whisper tests. Both multilingual `base` and `small` passed the upstream JFK speech recognition check and returned no transcript for actual silence. `pip check` found no broken requirements. Compilation and CLI help checks passed.

```sh
PATH="/tmp/clipper-media-tools:$PATH" CLIPPER_WHISPER_MODEL=/tmp/clipper-whisper-base CLIPPER_SPEECH_SAMPLE=/tmp/clipper-jfk.flac .venv/bin/python -m pytest -q -rs
PATH="/tmp/clipper-media-tools:$PATH" CLIPPER_WHISPER_MODEL=models/small CLIPPER_SPEECH_SAMPLE=/tmp/clipper-jfk.flac .venv/bin/python -m pytest -q tests/test_whisper_integration.py
.venv/bin/python -m pip check
python3 -m compileall -q clipper.py media.py youtube_source.py watch.py tests
```

FFmpeg and FFprobe 8.0 arm64 are installed temporarily at `/tmp/clipper-media-tools`, not globally. Runtime packages were installed into the project's ignored `.venv`. Installed versions include yt-dlp 2026.10.26, yt-dlp-ejs 0.8.0, faster-whisper 1.2.1, CTranslate2 4.8.5, NumPy 2.4.6 and ONNX Runtime 1.31.1.

## Actual replay evidence

The user supplied `https://www.youtube.com/watch?v=JX4Js8xAXdw&t=1217s` for authorized processing. YouTube reported a public, completed replay; FFprobe measured **10,540.628 seconds** (about 2h56m). The timestamp query does not limit analysis: the whole replay is processed.

- Actual yt-dlp metadata and download succeeded using Node 24 with the installed EJS component.
- The download was intentionally interrupted with SIGINT after 857,079,920 bytes. That partial file remained; the same command restarted at **35.1%**, rather than zero.
- The validated merged source is `shorts/_youtube_downloads/JX4Js8xAXdw.mkv` (2,600,902,739 bytes; retained locally).
- An identical URL rerun reused the source and all three successful base-model drafts. Source/output sizes and nanosecond modification times were unchanged. That verification run took **19.67 seconds**, with reported maximum RSS **372,424,704 bytes** on this Mac.
- A currently live NASA stream (`ROboUHfPUrU`) was rejected with a replay-not-ready error before media download. A malformed ID was rejected by the CLI. An unavailable/private test link also returned an actionable metadata error; no authentication bypass was attempted.

Real validation exposed and fixed three issues: missing EJS/runtime setup, capped scores that flattened strong peaks into early chronological ties, and low-confidence/repeated Whisper text. Pipeline version **1.3** retains stronger-peak ordering, uses temperature-zero decoding, and omits likely hallucinations (average log probability below -1, compression ratio above 2.4, or no-speech probability above 0.6). Omitted captions produce explicit warnings, retained when clips are reused. These gates reduce errors; they do not establish transcript accuracy.

## Current review drafts

Current pipeline 1.3 output using the local multilingual `small` model:

`shorts/JX4Js8xAXdw_ff54982d2295/`

| File | Source interval | Review status |
| --- | --- | --- |
| `short_01.mp4` | 183–219 seconds | review_required |
| `short_02.mp4` | 369–405 seconds | review_required |
| `short_03.mp4` | 2302–2338 seconds | review_required |

The model is retained at ignored `models/small`. Rerun from the project root with:

```sh
PATH="/tmp/clipper-media-tools:$PATH" .venv/bin/python clipper.py --input "https://www.youtube.com/watch?v=JX4Js8xAXdw&t=1217s" --output ./shorts --max-shorts 3 --model models/small
```

Captions are omitted where speech decoding fails the quality checks. The `base` run rejected all three transcripts for this noisy mixed-audio selection; `small` retained a Hindi draft transcript after filtering. Draft captions still require human correction. Earlier folders from pre-fix pipeline versions are validation experiments, not the current recommended outputs.

Synthetic and actual render checks verify portrait geometry, codecs, audio energy, duration, faststart, subtitle escaping, and full decode without errors. Rendered frames were inspected for complete HUD/source visibility and separation of headline/gameplay/captions. Synthetic Hindi displayed correctly on this Mac; an emoji showed a missing-glyph box. Actual caption accuracy and perceived audio quality still need the uploader's review.

## Windows gate and scope

The private Windows workflow installs Python 3.11, Node 24, FFmpeg, Python requirements and public test model/audio, then runs the same suite. Workflow YAML parses and its permissions/runner/triggers were checked locally. The final small-model run took 49.96 seconds on this Mac, with reported maximum RSS 863,322,112 bytes; the recorded peak memory footprint was 954,402,424 bytes. These measurements cover this host, not a Windows gaming PC. Native execution results must be recorded after the workflow runs; the YAML alone is not a pass.

Windows prerequisites now explicitly include the Visual C++ x64 runtime required by CTranslate2 and a supported JS runtime. Recordings, model weights, local environments and draft MP4s are excluded from the source push.

Selection remains a heuristic: a high-energy loot or movement moment may outrank a visually interesting fight. No kill/virality guarantee, word-level alignment, automatic public upload, dashboard, cloud application deployment or live capture was added. A Windows hosted-runner check does not substitute for performance/font checks on every Windows 10/11 gaming PC. All output remains review-required.
