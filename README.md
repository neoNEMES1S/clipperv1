# Fortnite Clipper

Generate **0–3 review-required vertical Shorts** from a completed YouTube livestream replay, or a local OBS recording. Paste the replay URL into one command after setup. Everything runs locally except the replay download and first-use Whisper model download. Nothing uploads or publishes videos.

This is an explainable candidate finder, not a kill detector or a guarantee of entertaining clips. Mixed gameplay audio can trigger false positives. It returns zero drafts when the signals are insufficient.

## Windows quick start

Install Python 3.11+, FFmpeg (including FFprobe and the `subtitles`/libass filter), and Deno 2.3+ (or Node.js 22+) on PATH. Current YouTube extraction needs a JavaScript runtime and the EJS scripts installed by `yt-dlp[default]`; see the [official yt-dlp setup guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS). Deno installation instructions are at [deno.com](https://docs.deno.com/runtime/getting_started/installation/). For example, install an FFmpeg distribution from [FFmpeg downloads](https://ffmpeg.org/download.html). On Windows, faster-whisper also requires the [Microsoft Visual C++ x64 runtime](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist/), as documented by [CTranslate2](https://opennmt.net/CTranslate2/installation). Use 64-bit Python. Open PowerShell in this folder and perform the one-time setup:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-combat.txt
ffmpeg -version
ffprobe -version
deno --version # Or: node --version (22+)
ffmpeg -filters | Select-String subtitles
```

After ending your stream, wait until its replay plays normally on YouTube. Run:

```powershell
.\.venv\Scripts\python.exe clipper.py --input "https://www.youtube.com/watch?v=YOUR_VIDEO_ID" --output ".\shorts" --max-shorts 3 --model small --combat-only
```

Replace `YOUR_VIDEO_ID` with the real 11-character ID. `https://youtube.com/live/VIDEO_ID` and `https://youtu.be/VIDEO_ID` also work. Use footage you own or are authorized to process. No separate OBS recording or isolated microphone track is required for URL mode.

With `--combat-only`, the program checks metadata, downloads/reuses a validated source, scans the personal HUD counter, confirms local elimination/knockdown notices, selects candidates, transcribes selected clips, and renders drafts. Conversation alone cannot anchor a combat clip. Without this flag, selection retains the original audio-energy heuristic. Progress is printed as `validate → download → analyze → select → transcribe → render → done`. A first Whisper run downloads model weights; later runs use the local model cache. CPU rendering can take longer than the clip duration.

These commands use the virtual environment's Python directly, so PowerShell activation is unnecessary. On macOS/Linux, create the environment with `python3 -m venv .venv` and use `.venv/bin/python` instead.

## Combat-first selection

Use `--combat-only` for kill/fight highlights. Install `requirements-combat.txt`: it adds small bundled RapidOCR models that run locally on CPU, without a Tesseract binary or a remote inference API.

```powershell
.\.venv\Scripts\python.exe clipper.py --input "https://youtu.be/YOUR_VIDEO_ID" --output ".\shorts" --combat-only --model small --max-shorts 3 --pre-roll 28 --post-roll 8
```

This mode reads the skull/personal-eliminations counter every two seconds. It requires two agreeing reads, ignores initial counts, resets, implausible jumps and long HUD gaps, and then looks for an elimination/knockdown notification in the center HUD near that increase. The left-side kill feed is excluded. Multi-kill groups outrank louder conversation; audio is only secondary evidence. It returns zero clips if no events meet those conditions, and fails clearly if the required OCR cannot run instead of falling back to conversation.

The counter crop is calibrated for the standard English HUD used in the tested 1280×720 replay. Custom HUD placement, visibility changes, brief notifications and unreadable digits can cause missed kills. This is a conservative heuristic, not a trained Fortnite event detector or a guarantee of the best moments. Review each output.

Completed visual scans are cached in `_combat_scans/` using source identity and detector version. Changing model or window settings reuses the scan. An interrupted scan restarts, while its downloaded source is retained. Delete the corresponding scan JSON to force fresh OCR after changing a HUD layout.

## Analyze, tune, and render

Analyze timestamps without loading Whisper or rendering MP4s. **URL mode still downloads the replay** for audio analysis:

```powershell
.\.venv\Scripts\python.exe clipper.py --input "https://youtu.be/YOUR_VIDEO_ID" --output ".\shorts" --max-shorts 3 --combat-only --dry-run
```

For English/Hindi code-switching, try multilingual `small` for potentially better accuracy at greater CPU/RAM cost. Accuracy is not guaranteed. Leave the model's language detection enabled; no external AI API is needed.

```powershell
.\.venv\Scripts\python.exe clipper.py --input "https://youtu.be/YOUR_VIDEO_ID" --output ".\shorts" --model small
```

The legacy `--ocr` broad HUD scan requires Tesseract installed on PATH and optional Python dependencies. It can read other players' kill-feed messages; use `--combat-only` for the confirmed-counter workflow above:

```powershell
.\.venv\Scripts\python.exe -m pip install opencv-python-headless pytesseract
.\.venv\Scripts\python.exe clipper.py --input "https://youtu.be/YOUR_VIDEO_ID" --output ".\shorts" --ocr
```

OCR samples roughly every eight seconds for English victory/elimination phrases. It can miss brief events or misread the HUD. Missing OCR dependencies or decoding errors produce a warning in the log and manifest; audio-only processing continues.

Default windows contain up to 23 seconds before and 13 seconds after an event, clamped to source duration, with a minimum of eight seconds. Tune a small set of parameters:

```powershell
.\.venv\Scripts\python.exe clipper.py --input "https://youtu.be/YOUR_VIDEO_ID" --output ".\shorts" --pre-roll 20 --post-roll 15 --min-clip-seconds 8 --peak-ratio 1.8 --peak-spacing 20
```

- `--max-shorts 3`: maximum number selected; zero is permitted for analysis only.
- `--peak-ratio 1.4`: minimum energy relative to recording and local floors; values must exceed one. Higher values reduce detections.
- `--peak-spacing 14`: minimum seconds between audio peaks.
- `--pre-roll 23`, `--post-roll 13`: maximum window length is their sum.
- `--min-clip-seconds 8`: discard shorter edge windows or short sources.
- `--no-transcribe`: testing mode; omits speech captions, retains the headline.

Use `python clipper.py --help` for all flags. Negative track indices, invalid clip lengths and non-finite detection parameters are rejected before downloading.

## What selection means

Analysis reads mono 16-bit/16 kHz audio in one-second chunks. Only the per-second energies are kept in RAM. Peaks must pass a recording-relative energy threshold, a local prominence check, a minimum loudness floor, and spacing suppression. Silence and constant volume produce no events.

Each manifest event exposes `time_seconds`, `signal_type`, `raw_score`, `normalized_score` (0–1), and evidence. `mic_reaction` is the legacy signal name for audio energy; **it does not prove speech or a microphone reaction**, especially for YouTube mixed audio. OCR evidence is the recognized text, not verified gameplay.

Nearby events within ten seconds and inside the window are combined. The strongest event of each signal type contributes once; repeated OCR/audio hits do not accumulate extra confidence. Weights in `clipper.py` are `mic_reaction=1.0`, `victory_ocr=0.9`, `elimination_ocr=0.75`, with a `0.3` bonus per additional independent signal type. Audio normalization uses a monotonic ratio/(1+ratio), so strong peaks keep their ordering instead of all hitting a score cap. These are heuristic ranking scores, not probabilities. Overlapping windows are suppressed (at most four seconds of overlap); the strongest survive and outputs follow source chronology.

Whisper runs **only on selected clips**, with voice activity filtering. Greedy decoding uses temperature zero to avoid sampling different text on retries. Text with average log probability below -1, compression ratio above 2.4, or no-speech probability above 0.6 is omitted instead of burning in likely hallucinations. Empty/low-confidence results are recorded as warnings; these checks reduce bogus captions but cannot guarantee accuracy. Captions use approximate segment-based timing and small word groups, not word alignment. Empty transcripts produce a headline-only video. Output is H.264/AAC MP4, 1080×1920, 30 fps, yuv420p, faststart. The whole gameplay frame fits over a blurred background, preserving the HUD instead of cropping it. Headline and captions stay above typical mobile controls. Font coverage depends on your OS; install a Devanagari-capable font such as Nirmala UI or Noto Sans Devanagari for Hindi. Emoji appearance also depends on available fonts.

## Outputs, manifests, and retrying

```text
shorts/
  clipper.log                         # CLI errors, including download failures
  _youtube_downloads/
    VIDEO_ID.mkv                      # validated source cache
    _partial/VIDEO_ID/                 # resumable download/merge work
  _combat_scans/                       # completed, source/version-checked visual scans
  VIDEO_ID_<source-and-config-hash>/
    short_01.mp4                      # only when a candidate rendered successfully
    manifest.json
    posting_notes.md
    processing.log
```

Job identity includes the video ID/local filename, source path/size/modification time, pipeline version, and processing settings. Different models, detection settings, or dry runs get separate directories. Re-running the same command reuses a valid source cache and validated successful clips; failed or missing clips are retried. Unrelated job outputs are preserved. Editing draft titles/descriptions in a successful manifest carries those edits into an identical rerun. Do not run multiple processes for the same source/output simultaneously.

`manifest.json` schema version `1.0` contains:

| Field | Meaning |
| --- | --- |
| `source` | `type`, original `url`, `video_id`, local `path`, `downloaded_source_path`, and validated `duration_seconds` |
| `config` | Pipeline version, Whisper model name, tracks, detection weights/parameters, OCR and analysis/transcription flags |
| `status` | `created` for analysis/no candidates, `review_required` for rendered drafts, `failed` for processing failure; never a publishing status |
| `events` | All detected event times, raw/normalized strengths and evidence |
| `candidates` | Selected windows: `start`/`end` plus `start_seconds`/`end_seconds`, anchor, score, signals and nearby evidence |
| `shorts` | Each draft's ID, relative `path`/`filename`, source times, score, signals, transcript, caption timings, editable title/description, and status |
| `warnings`, `error` | Optional OCR warnings and processing failure details |
| `output_directory` | Absolute job output folder |

Root `source_url`, `duration_seconds`, and `audio_tracks` remain for convenience. Source is now a structured object instead of the original path string. Dry runs have candidates and an empty `shorts` array; they never claim MP4s exist. `created` can also be an in-progress state: inspect the final console/log message. Interrupted runs may retain that state until rerun. A failed clip has `failed` status, while earlier successful clips remain `review_required`. `posting_notes.md` summarizes status, file names, titles, descriptions, source times and transcripts; review everything before posting. A `POSSIBLE` OCR title is explicitly tentative; no “1 HP” claims are inferred from speech.

Manifests are replaced atomically. Rendering writes a temporary MP4 and validates format/duration before replacing the final file. FFmpeg stderr and Python failures are retained in the logs. The source is retained on failure. FFprobe checks stream/container metadata; this is not a full-frame corruption scan.

## YouTube reliability and storage

Only a single accessible, completed video/replay is accepted. Playlists (including video links with `list=`), malformed IDs, non-YouTube hosts and remote schemes other than HTTP/HTTPS are rejected. Ongoing, upcoming, and still-processing `post_live` streams are rejected; try again after the replay becomes playable. Private, removed, or otherwise restricted content is unsupported. There is no authentication or access-control bypass.

Downloads use a stable video-ID cache and a separate partial directory. A cache hit must pass FFprobe checks for readable metadata, positive duration, video and audio. Corrupt entries are replaced only after a new download validates. Metadata is still checked on every URL run, so rerunning a URL requires connectivity even if the media is cached. For offline processing, pass the cached path with `--mic-track 0`.

Video storage depends on bitrate: at 8 Mb/s, one hour is approximately 3.6 GB. Allow roughly twice the source size during download/merge, plus drafts and temporary analysis audio (about 115 MB per hour). Temporary audio uses the system temp directory and is removed after analysis. Whisper model weights occupy additional space in its model cache. Interrupted downloads can retain partial files for resume.

The source cache is kept by default. To remove the cached full replay **only after a successful non-dry-run job**, use:

```powershell
.\.venv\Scripts\python.exe clipper.py --input "https://youtu.be/YOUR_VIDEO_ID" --output ".\shorts" --delete-download
```

This flag also deletes the source after a successful full analysis that found zero candidates; it is ignored for dry runs. It never deletes local inputs. Historical source paths in the manifest remain after explicit deletion. For manual cleanup, stop active jobs, then remove unwanted job directories or `_youtube_downloads/_partial` entries; deleting cache files means another download on the next URL run.

For network/HTTP failures, first check that the replay is publicly playable and you have free disk space. If an accessible replay fails, update yt-dlp with `python -m pip install -U "yt-dlp[default]"`. For tool errors, verify FFmpeg/FFprobe are on PATH and `ffmpeg -filters` includes `subtitles`. The downloader enables Deno and Node.js; install one supported version if the diagnostic says no runtime is available. No JavaScript solver code is fetched dynamically by this app; EJS is installed through the Python requirement.

## Optional local OBS workflow

Local files keep the original defaults: `--mic-track 1` (second audio stream, isolated mic), `--mix-track 0` (first stream, game+mic). Configure OBS to record both tracks. If your local recording only has mixed audio, pass `--mic-track 0`.

```powershell
.\.venv\Scripts\python.exe clipper.py --input "D:\FortniteClips\recording.mkv" --output ".\shorts" --mic-track 1 --mix-track 0 --max-shorts 3
```

`0:a:N` counts audio streams from zero, not FFprobe's global stream indexes. Inspect your streams with:

```powershell
ffprobe -v error -select_streams a -show_entries stream=index,codec_name -of json "D:\FortniteClips\recording.mkv"
```

The optional directory watcher retains its CLI:

```powershell
.\.venv\Scripts\python.exe watch.py --recordings "D:\FortniteClips\recordings" --output ".\shorts" --mic-track 1 --stable-seconds 90
```

It waits for stable file size/modification time, not an OBS stop event. Long recording pauses may trigger it early. Existing recordings may be processed once. Failures are persisted in `.processed_recordings.json` to avoid retry storms; stop the watcher and remove the corresponding failed entry to retry. Restarting alone does not clear a failed entry.

## Testing and release gate

The current implementation has passed 76 tests and 22 subtests locally and on a native Windows CI runner, with no skips, plus full processing of the supplied four-hour replay in combat mode. See [implementation and validation evidence](IMPLEMENTATION_REPORT.md) for exact versions, run links, draft locations and limits.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-combat.txt
.\.venv\Scripts\python.exe -m pytest -q -rs
```

Unit tests mock yt-dlp and Whisper and require no network/model downloads. FFmpeg smoke tests generate synthetic 16:9 media, check portrait H.264/AAC output, audio presence, duration, faststart, captions, real corrupt/no-audio inputs, and local CLI rerun behavior. They skip with an explicit reason if FFmpeg or FFprobe is unavailable.

For opt-in tests with real Whisper inference, download the `base` model and the upstream public speech fixture, then provide their local paths. Normal unit tests remain offline and skip these two checks unless explicitly enabled:

```powershell
.\.venv\Scripts\python.exe -c "from faster_whisper.utils import download_model; download_model('base', output_dir='models/base')"
Invoke-WebRequest "https://raw.githubusercontent.com/openai/whisper/main/tests/jfk.flac" -OutFile "models/jfk.flac"
$env:CLIPPER_WHISPER_MODEL = (Resolve-Path "models/base").Path
$env:CLIPPER_SPEECH_SAMPLE = (Resolve-Path "models/jfk.flac").Path
.\.venv\Scripts\python.exe -m pytest -q -rs
```

These integration checks require successful speech recognition with valid timestamps and an empty result for actual silence. `--model` also accepts a local CTranslate2 model directory for offline processing.

The `.github/workflows/windows-tests.yml` installs Python 3.11, Node 24, FFmpeg, runtime dependencies and the public test model/sample on a Windows runner, then runs the full suite. It does not download user recordings or publish videos. A successful run is still required to validate Windows execution; merely adding the workflow is not evidence of a pass.

Before calling this ready for real streams, process a **user-owned, completed Fortnite replay** and manually review the generated drafts for HUD visibility, caption timing/Hindi font rendering, audible mixed audio and useful selection. Check actual files/times against the manifest, run the command again to confirm cache/clip reuse, and try an invalid/live link to verify the error. Automated synthetic tests do not establish real YouTube download compatibility, transcription accuracy, or highlight quality. Windows installation and real replay review must be checked on the target machine.

A dashboard, gameplay model training, real-time capture, cloud deployment, and uploads are outside this release.
