# Gaming Clipper

Generate vertical clips from completed YouTube replays or local OBS recordings. Clipper runs on your computer and produces captioned MP4 drafts for review. The browser dashboard supports Fortnite and GTA 6, and the command line also accepts local video files. Basic clipping needs no API keys or publishing accounts.

Use footage you own or have permission to process and publish. The clip limit is a maximum. Depending on the footage and settings, fewer moments may qualify.

## Quick start

Download the source from GitHub or clone it with Git. Run the setup commands from the project folder.

```sh
git clone https://github.com/neoNEMES1S/clipperv1.git
cd clipperv1
```

### Requirements

- [Python 3.11](https://www.python.org/downloads/) is the version used by the Windows test workflow.
- [FFmpeg and FFprobe](https://ffmpeg.org/download.html) must be on `PATH`. Use a build with the `subtitles` filter (`libass`) and the `libx264` encoder.
- For YouTube replays, install [Deno 2.3+ or Node.js 22+](https://github.com/yt-dlp/yt-dlp/wiki/EJS) and add it to `PATH`. The Python requirements install `yt-dlp` and its EJS scripts.
- For GTA 6 story analysis and generated headlines, set up [Ollama](#local-ai-setup). Fortnite combat detection and basic local CLI clipping can run without it.

### Windows

Install 64-bit Python 3.11, the [Microsoft Visual C++ x64 Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist), and the tools above. Open a new PowerShell window after changing `PATH`.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-combat.txt
ffmpeg -hide_banner -filters | Select-String subtitles
ffprobe -version
deno --version # Use node --version if you installed Node.js.
.\.venv\Scripts\python.exe app.py
```

After setup, you can also double-click **Start Clipper.bat**.

### macOS

With [Homebrew](https://brew.sh/), install the full FFmpeg build for subtitle rendering. Add its `bin` directory to `PATH` before starting Clipper in Terminal.

```sh
brew install python@3.11 ffmpeg-full deno
export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-combat.txt
.venv/bin/python app.py
```

For later launches, keep that `PATH` setting in your shell configuration or use the same Terminal setup. **Start Clipper.command** can also launch the dashboard when FFmpeg and FFprobe are available to it, including through `.local/bin/`.

### Linux

Use your system package manager to install Python 3.11 with `venv` support and the tools listed above. Check that `ffmpeg -hide_banner -filters` lists `subtitles` before running Clipper.

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-combat.txt
.venv/bin/python app.py
```

### Local AI setup

Install and start [Ollama](https://docs.ollama.com/quickstart). If you installed only the CLI and there is no running service, start `ollama serve` in a separate terminal. Then download the model Clipper uses for story analysis and titles.

```sh
ollama pull qwen3-vl:2b-instruct
ollama list
```

Clipper calls Ollama on `127.0.0.1:11434`. Leave it running during GTA 6 processing. Whisper downloads its model the first time it transcribes audio and reuses it on later runs.

## Local dashboard

Once Clipper starts, open [the local dashboard](http://127.0.0.1:8765). The dashboard defaults to a limit of 25 clips and the CLI defaults to three.

1. Choose **Fortnite** or **GTA 6**, then paste a completed YouTube replay URL. For GTA 6, optionally enter a **Stream brief**, such as “How to make money in GTA 6.”
2. Choose a clip limit (1–100, default 25). In GTA 6 mode, click **Find story cuts**. Select the proposed stories you want, adjust the source times if needed, then click **Render selected stories**. Fortnite still renders confirmed eliminations directly.
3. Play or download the rendered clips, or open their output folder. Use **Clip batches** to return to earlier results.

When revisiting an older highlight to include more context, clear **Skip footage already clipped from this stream** before starting a new analysis.

The dashboard initially selects GTA 6 and remembers your game choice in this browser. Check the Game field before generating: Fortnite mode requires a confirmed elimination counter and can reject GTA footage even when audio peaks exist. Progress logs identify the game being processed. The CLI continues to default to Fortnite; pass `--game gta6` for GTA footage.

To change the text at the top of an existing Short, edit **Top headline** underneath its preview and click **Save & re-render**. Leave it blank to remove the headline. Use up to 72 characters that fit within three short lines. Only that clip is rendered again from the retained original replay; timing, mixed audio and saved speech captions are preserved. The preview/download refreshes after completion. The first edit saves `short_01.original.mp4` (and equivalent names) beside the clip as a permanent original backup. Re-running the same processing job retains the edited headline. This editor changes the top headline; it does not edit the speech transcript.

Keep the launcher/terminal window open while processing. Closing the browser tab does not stop a job. Press Ctrl+C in the launcher to stop the server and active processing. Completed clips and source downloads are retained. The first GTA 6 analysis transcribes the full stream with the small multilingual Whisper model and saves the timestamped transcript in `shorts/_transcripts/`. Revisiting the same source can reuse that transcript.

Saved replays are remembered on disk in `shorts/_youtube_downloads/` by YouTube video ID. After restarting Clipper, paste the same stream URL and click **Generate clips**: a valid saved replay is reused before any YouTube request, then analysis and clip generation continue. Watch, live-replay and shortened URLs for the same video share that file, across both games. Progress reports when the download is skipped. Keep this folder to retain your streams; missing or invalid media is downloaded again. An identical run reuses validated completed clips and preserves edited headlines.

GTA 6 story analysis uses the local Ollama model to find setup, key steps, and a result in the transcript. It checks sampled gameplay frames near suggested boundaries. An editorial brief limits which cuts qualify. Review stories with an unconfirmed ending before rendering. If no stories are found and the brief is empty, Clipper can propose cuts around audio peaks. GTA 6 mode requires no Fortnite OCR dependencies.

For GTA 6 from the Mac/Linux CLI:

```sh
.venv/bin/python clipper.py --input "https://youtu.be/YOUR_VIDEO_ID" --output shorts --game gta6 --model small --auto-title --story-brief "How to make money in GTA 6"
```

Review and render the proposed batch from the dashboard. On Windows use `.\.venv\Scripts\python.exe`. The CLI still defaults to Fortnite. For the previous audio-led GTA 6 mode, omit `--story-brief`. `--combat-only` and `--ocr` are Fortnite-only options.

Clipper binds to `127.0.0.1` and serves completed clips from the output manifests. Detailed pipeline logs are saved with the batch. For headless use, run `app.py --no-browser` with the virtual environment’s Python. For private remote use, forward the loopback port through SSH and open the forwarded address on your own device. The setup above runs Clipper as a local process. Running it at boot requires configuring your operating system’s task scheduler or service manager.

If port 8765 is occupied, close the previous launcher or start Clipper with `app.py --port 8766`. FFmpeg and FFprobe can also be placed in the ignored `.local/bin/` folder. Use `.exe` on Windows.

## Automatic clip titles

The dashboard drafts each new clip's title from four sampled gameplay frames and its Whisper transcript, using **Qwen3-VL 2B through local Ollama**. The headline is burned into the clip and also used for its posting title. Review it in **Top headline**, edit if needed, and choose **Save & re-render** before posting. The model can misinterpret gameplay; a suggested title is not a verified event description.

Clipper sends title-generation frames and transcripts to local Ollama. The vision model is about 1.9 GB. If Ollama is unavailable or cannot identify a clear action, Clipper keeps the generic headline and records a warning. See [Local AI setup](#local-ai-setup).

For CLI runs, add `--auto-title` to enable this step. It is off by default in the CLI. Dry runs never call the vision model. Automatic-title runs have separate identities from older generic-title runs, preserving the older clips. Repeating the same automatic-title run reuses completed clips and preserves any manually edited headline.

## Publish to YouTube and Instagram

Install the optional publishing dependencies once, then restart Clipper:

```sh
.venv/bin/python -m pip install -r requirements-publish.txt
```

On Windows use `.\.venv\Scripts\python.exe -m pip install -r requirements-publish.txt`. These dependencies include the combat pipeline. The browser interface still needs no frontend packages or build step.

This checkout verifies publishing destinations against `YOUTUBE_HANDLE` and `INSTAGRAM_HANDLE` in [`publish_accounts.py`](publish_accounts.py). To publish to your own accounts, set those constants to your handles without `@` before starting Clipper. You can also update the display labels in [`web/index.html`](web/index.html). The clipping and MP4 download workflow works without publishing setup.

Open the **YouTube**, **Instagram**, and **Temporary storage** cards under **Publish your clips**. Enter credentials in the local dashboard. Clipper reads publishing credentials from the OS credential store.

- **YouTube.** Enable YouTube Data API v3 in your Google Cloud project and create a **Desktop app** OAuth client. If the consent screen is in testing, add your Google account as a test user. Import the client JSON, choose **Connect YouTube**, and sign in to the channel you configured. Clipper requests upload and channel-read permissions and verifies the channel ID. [Google desktop OAuth setup](https://developers.google.com/identity/protocols/oauth2/native-app)
- **Instagram.** Connect a professional account using the login method configured for your Meta app. For **Unified Login**, use a token with `instagram_basic` and `instagram_content_publish`, and leave the app secret field empty. Clipper verifies that the shared account matches your configured handle. Reconnect when Meta expires or revokes the token. [Meta Unified Login setup](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-unified-login/get-started)
- **Older Instagram Login apps:** select **Instagram Login**, with `instagram_business_basic` and `instagram_business_content_publish`. The optional app secret exchanges a short-lived token for a long-lived token and is not retained. Known long-lived tokens refresh near expiry; tokens entered without an exchange have unknown expiry and may need manual reconnection. Existing saved connections continue using this method.
- **Temporary storage:** enter your HTTPS S3-compatible endpoint without a bucket path, bucket, region (`auto` for R2), and access/secret keys. Use a private bucket and credentials with PutObject, GetObject and DeleteObject access to Clipper’s `clipper/` prefix. Temporary AWS session credentials are not supported. “Configured” means saved; connectivity is checked during upload. Clipper does not change bucket ACLs or policies. [Instagram Login publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing/) requires Meta to fetch an HTTPS media URL; Clipper stages only the selected clip and creates a one-hour signed fetch URL.

Credentials and YouTube resumable session URLs are saved through the native OS credential store (macOS Keychain / Windows Credential Manager). Plaintext fallback is refused. If the OS store asks for access, approve it locally. **Disconnect** removes the saved account token; it does not revoke permissions at Google/Meta. Google’s client configuration remains available locally for reconnection.

Choose **Publish clip →** below a completed preview. Edit the posting title/description/caption, choose YouTube, Instagram, or both, and set visibility/audience. These fields do not change the burned-in top headline. YouTube defaults to **Private**; the audience choice has no default. **Review upload** shows the exact clip version, accounts and posting text. **Upload now** starts the transfer. Instagram publishes a Reel immediately, including to the feed; there is no draft or scheduling mode. YouTube may keep processing the video after transfer completes.

Upload history records each platform separately and provides post links and **Review & resume**. An identical file is uploaded at most once per saved destination account. Resumes use frozen reviewed bytes and saved posting details, even after a later headline edit. A changed file is a new version and can create a new post. If YouTube’s resumable session expires or a provider cannot confirm publication, check the account before attempting a fresh upload; Clipper refuses to create a possible duplicate automatically. If an Instagram publish is confirmed without a post ID, history links to the account instead of inventing a Reel link.

After publication Clipper deletes its own staged Instagram object. If deletion fails, history keeps the successful publication and offers **Retry cleanup**, which does not publish again. Interrupted/failed uploads can leave a staged object until resumed; use a bucket lifecycle rule if you also want provider-side expiry. The signed URL expiring does **not** delete the object. Existing unrelated bucket objects are never deleted.

Public connection metadata and upload receipts are stored in ignored `.local/publishing.sqlite3`. Frozen clips and Instagram upload copies remain in `.local/publish_media/` for retries. Keep this state to retain duplicate protection and history, and budget disk space for the copies. Publishing starts when you confirm a reviewed upload. Clipper sends the selected rendered clips.

## Combat-first selection

Use `--combat-only` for kill/fight highlights. Install `requirements-combat.txt`: it adds small bundled RapidOCR models that run locally on CPU, without a Tesseract binary or a remote inference API.

```powershell
.\.venv\Scripts\python.exe clipper.py --input "https://youtu.be/YOUR_VIDEO_ID" --output ".\shorts" --combat-only --model small --max-shorts 3 --pre-roll 28 --post-roll 8
```

Replace `YOUR_VIDEO_ID` with a completed replay’s 11-character ID. For the CLI examples below, macOS and Linux users can substitute `.venv/bin/python` and use `shorts` as the output path.

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

Downloads use a stable video-ID cache and a separate partial directory. A cache hit must pass FFprobe checks for readable metadata, positive duration, video and audio. Corrupt entries are replaced only after a new download validates. A valid saved replay skips both YouTube metadata requests and downloading, including after an application restart. Only cache misses require YouTube connectivity and replay-availability checks. Offline processing also needs the selected Whisper model already cached (or `--no-transcribe`).

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

## Testing

The [Windows CI workflow](.github/workflows/windows-tests.yml) covers the dashboard API, synthetic FFmpeg rendering, Whisper integration, and publishing protocols with mock provider responses. See [the validation report](IMPLEMENTATION_REPORT.md) for previous test runs. For an installation smoke test, process a completed replay you own and review the generated drafts for audio, caption timing, and clip boundaries.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-publish.txt
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
