# Combat-selection follow-up — 2026-11-12

User review showed that the initial audio-only ranking selected conversation/looting instead of meaningful fights. Passing the original encoding/unit tests did not establish highlight relevance. Pipeline 1.4 adds an explicit `--combat-only` workflow.

## Four-hour replay

Processed the complete user-supplied replay `https://www.youtube.com/watch?v=2GaAaYYtUK4` (FFprobe duration **14952.328 seconds**, about **4h09m**). The downloaded source is retained under `shorts/_youtube_downloads/2GaAaYYtUK4.mkv`.

The scanner found **39 stable personal-counter increases** and retained **25** with a matching local elimination/knockdown notification. The left kill feed is excluded. The personal skull counter is used, not the adjacent squad total. Two agreeing reads, confidence thresholds, reset/gap handling and local notice confirmation reject ambiguous signals. Conversation alone cannot anchor a combat clip. Multi-kill groups rank higher; speech contributes only a small secondary bonus.

The first-ten-minute calibration was visually checked against a real tower fight with `ELIMINATION X3`, confirming a personal counter change from 3 to 6. Small bundled RapidOCR ONNX models run locally; footage is not sent to an OCR API and this mode does not require a Tesseract executable. Standard English HUD placement is required. Completed scans are cached by source identity and detector version.

## New outputs

`shorts/2GaAaYYtUK4_0f95a7c27909/`

| File | Source interval | Evidence |
| --- | --- | --- |
| `short_01.mp4` | 7:02–7:38 | Personal 3→6; center `ELIMINATION X3`; tower shotgun fight |
| `short_02.mp4` | 1:04:18–1:04:54 | Personal 3→7; center `ELIMINATION X4` |
| `short_03.mp4` | 3:41:00–3:41:36 | Personal 5→8; local elimination notice; rendered frame shows `TRIPLE ELIM` and enemy team wiped |

All three are 36-second, review-required drafts. Complete video/audio decoding passed. Rendered frames were inspected for combat, visible HUD, layout and safe headline placement. Whisper rejected all three noisy mixed-audio transcripts under the quality gates, so speech captions are omitted and warnings are recorded. Original mixed gameplay audio is retained. These are evidence-backed candidates, not a guarantee of the most entertaining moments.

The complete scan/transcription/render pass, after downloading, took **352.35 seconds** on this Mac. Reported maximum RSS was **1,506,721,792 bytes**. Repeating the same command reused the downloaded source, completed visual scan and all three MP4s; none of their modification times changed. **76 tests passed locally**, plus **22 subtests**, with no skips. `pip check` passed. Automated coverage now includes combat gating, false kill-feed exclusion, scan cache validation, fail-closed behavior, actual OCR glyph recognition and a synthetic-video-to-confirmed-event test. The updated [Windows run 43194355019](https://github.com/neoNEMES1S/clipperv1/actions/runs/43194355019) also passed **76 tests and 22 subtests**, with no skips, in **21.49 seconds**. Tested source commit: `f1faf7b35f5f03832e333a68d0cb592c469900ed`. It installed the combat dependencies and exercised native OCR through the synthetic-video scanner test. The Windows log is retained locally at `shorts/_validation/combat-windows-validation.log`.

Reproduce:

```sh
PATH="/tmp/clipper-media-tools:$PATH" .venv/bin/python clipper.py --input "https://www.youtube.com/live/2GaAaYYtUK4?si=fI1wRQ6G5xC6SE-_" --output ./shorts --max-shorts 3 --model models/small --combat-only --pre-roll 28 --post-roll 8
```

Install `requirements-combat.txt` for the extra OCR package. Exact source/candidate/version evidence is recorded in the new job's `validation.json`; full scan data is in `shorts/_combat_scans/`. Existing audio-only CLI behavior remains available without `--combat-only`; the README quick start now recommends combat-first processing for Fortnite fights.

This mode is conservative and can miss unreadable counters, the first kill before a readable baseline, custom/localized HUDs, or combat without a finished elimination. An interrupted scan restarts, while completed scans are reused. Source downloads remain resumable. No automatic upload, review dashboard, or external inference service was added.

---

# Initial pipeline 1.3 implementation and release validation (historical)

The core implementation, real-replay validation, local checks and native Windows CI are complete. The authorized repository is [private clipperv1](https://github.com/neoNEMES1S/clipperv1). [Windows CI run 42825513698](https://github.com/neoNEMES1S/clipperv1/actions/runs/42825513698) passed all 60 tests, plus 22 unittest subtests, with no skips. Nothing uploads or publishes videos.

## Implemented

- A: strict single-video URL/ID validation, completed-replay checks, validated stable-ID cache, staged/resumable downloads, atomic cache promotion and actionable errors.
- B: bounded-memory energy scanning, recording/local prominence, normalized explainable events, weighted multi-signal ranking, clamped/deduplicated windows and analysis-only dry runs.
- C: selected-clip local Whisper, safe Unicode/ASS formatting and clip-relative captions, complete gameplay frame over blur, 1080×1920 H.264/AAC/30fps/yuv420p/faststart output, validated atomic renders.
- D: versioned/configuration-specific jobs, manifests/notes/logs, honest draft titles, failed/review-required statuses and validated clip reuse.
- E: offline unit tests, real FFmpeg and Whisper checks, actual replay processing, interrupted-download resume, URL failures and a passing native Windows workflow.

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
- An identical URL rerun reused the source and all three successful base-model drafts. Source/output sizes and nanosecond modification times were unchanged. That base-model verification run took **19.67 seconds**, with reported maximum RSS **372,424,704 bytes** on this Mac. The final pipeline 1.3 small-model rerun also preserved every source/draft size and mtime, retained both caption warnings, and finished in **16.50 seconds** with maximum RSS **372,965,376 bytes**.
- A currently live NASA stream (`ROboUHfPUrU`) was rejected with a replay-not-ready error before media download. A malformed ID was rejected by the CLI. An unavailable/private test link also returned an actionable metadata error; no authentication bypass was attempted.

Real validation exposed and fixed three issues: missing EJS/runtime setup, capped scores that flattened strong peaks into early chronological ties, and low-confidence/repeated Whisper text. Pipeline version **1.3** retains stronger-peak ordering, uses temperature-zero decoding, and omits likely hallucinations (average log probability below -1, compression ratio above 2.4, or no-speech probability above 0.6). Omitted captions produce explicit warnings, retained when clips are reused. These gates reduce errors; they do not establish transcript accuracy.

## Initial audio-only drafts (superseded for content quality)

Historical pipeline 1.3 audio-only output using the local multilingual `small` model. User review found these inadequate for fights; use the combat-first follow-up above instead:

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

Captions are omitted where speech decoding fails the quality checks. The `base` run rejected all three transcripts for this noisy mixed-audio selection; `small` retained a Hindi draft transcript after filtering. Draft captions still require human correction. Earlier runs are archived under `shorts/_validation/earlier_runs/` and marked superseded; the folder above contains the historical pipeline 1.3 outputs.

All three final drafts passed complete video/audio decoding, source/caption timestamp bounds, and format checks. Their audio envelopes correlate with the corresponding original mixed-audio windows at 0.99986–0.99994, with zero measured offset at 10 ms resolution. Synthetic and actual render checks verify portrait geometry, codecs, audio energy, duration, faststart and subtitle escaping. Rendered frames were inspected for complete HUD/source visibility and separation of headline/gameplay/captions. Synthetic Hindi displayed correctly on this Mac; an emoji showed a missing-glyph box. Actual caption accuracy and perceived audio quality still need the uploader's review.

## Windows validation and review limits

The private Windows workflow installed Python 3.11, Node 24, FFmpeg, Python requirements and public test model/audio, then passed the complete suite on the `windows-2025-vs2026` hosted image. The 60 tests and 22 subtests completed in 25.32 seconds, with no skips. This validates real Whisper speech/silence behavior, synthetic rendering, retries/metadata and the CLI on Windows. Tested source commit: `56c6176fcb48ea54741496b97677ac60ae602241`. Workflow YAML parses and its permissions/runner/triggers were checked locally. The final small-model run took 49.96 seconds on this Mac, with reported maximum RSS 863,322,112 bytes; the recorded peak memory footprint was 954,402,424 bytes. These measurements cover this host, not a Windows gaming PC. The run logs are retained at `shorts/_validation/windows-validation.log`; structured evidence is at `shorts/_validation/release_evidence.json`.

Windows prerequisites now explicitly include the Visual C++ x64 runtime required by CTranslate2 and a supported JS runtime. Recordings, model weights, local environments and draft MP4s are excluded from the source push.

Selection remains a heuristic: a high-energy loot or movement moment may outrank a visually interesting fight. No kill/virality guarantee, word-level alignment, automatic public upload, dashboard, cloud application deployment or live capture was added. A Windows hosted-runner check does not substitute for performance/font checks on every Windows 10/11 gaming PC. All output remains review-required.
