# Fortnite Clipper

Generate **review-required vertical Shorts** from a completed YouTube livestream replay, or a local OBS recording. Use the local dashboard or the CLI after setup. The dashboard defaults to up to 25 clips; the CLI defaults to 3. Processing runs locally except replay/model downloads. The optional publishing panel uploads only a selected, reviewed clip after **Upload now**.

This is an explainable candidate finder, not a kill detector or a guarantee of entertaining clips. Mixed gameplay audio can trigger false positives. It returns zero drafts when the signals are insufficient.

## Local dashboard

After the one-time Python/FFmpeg setup below, double-click **Start Clipper.command** on Mac or **Start Clipper.bat** on Windows. On this Mac, the existing environment, small model, and local FFmpeg tools are already prepared. The launcher opens **http://127.0.0.1:8765** in your browser.

1. Paste a completed YouTube replay URL.
2. Choose a clip limit (1–100, default 25), then click **Generate clips**. The limit is a ceiling; only qualifying, distinct combat moments are selected.
3. Follow the real processing stages, then play/download clips or open their output folder. Use the run selector to revisit earlier results. Older audio-only runs are labelled separately.

To change the text at the top of an existing Short, edit **Top headline** underneath its preview and click **Save & re-render**. Leave it blank to remove the headline. Use up to 72 characters that fit within three short lines. Only that clip is rendered again from the retained original replay; timing, mixed audio and saved speech captions are preserved. The preview/download refreshes after completion. The first edit saves `short_01.original.mp4` (and equivalent names) beside the clip as a permanent original backup. Re-running the same processing job retains the edited headline. This editor changes the top headline; it does not edit the speech transcript.

Keep the launcher/terminal window open while processing. Closing the browser tab does not stop a job; reopening the page reconnects to it. Press Ctrl+C in the launcher to stop the server and active processing. Completed clips and source downloads are retained. One job runs at a time; the dashboard uses combat-only selection, the small multilingual Whisper model, and 28 seconds before / 8 seconds after each event.

The interface uses the Python standard library and local HTML/CSS/JS, with no Node build, frontend packages, remote fonts or CDNs. It binds only to loopback and serves completed clips from the output manifests. History survives restarts; live progress is held in memory, while detailed pipeline logs remain in the output folders. It is a local desktop utility, not a remotely hosted service.

If double-click launching is unavailable, run `.venv/bin/python app.py` on Mac/Linux or `.\\.venv\\Scripts\\python.exe app.py` on Windows. If port 8765 is already occupied, close the previous launcher or run `app.py --port 8766`. `--no-browser` starts just the server. FFmpeg/FFprobe can be on PATH or placed in the ignored `.local/bin/` folder (use `.exe` on Windows). Mac Homebrew executable paths are also checked.

## Publish to YouTube and Instagram

Install the optional publishing dependencies once, then restart Clipper:

```sh
.venv/bin/python -m pip install -r requirements-publish.txt
```

On Windows use `.\.venv\Scripts\python.exe -m pip install -r requirements-publish.txt`. These dependencies include the combat pipeline. The browser interface still needs no frontend packages or build step.

Open the **YouTube**, **Instagram**, and **Temporary storage** cards under **Publish your clips**. Enter credentials in this local page, never in chat or the remote design preview.

- **YouTube:** enable YouTube Data API v3 in your Google Cloud project; use a **Desktop app** OAuth client JSON. Add your Google account as a test user if the consent screen is in testing. Import the JSON and choose **Connect YouTube**. The system browser uses a loopback callback with PKCE and requests upload/channel-read permissions. Sign in to **@neonemesis8055**; Clipper checks the selected channel ID against that handle and rejects another channel. See [Google’s desktop OAuth setup](https://developers.google.com/identity/protocols/oauth2/native-app).
- **Instagram:** use the access token generated for **@tyler1butsane** through your Meta app’s **Instagram Login** setup, with `instagram_business_basic` and `instagram_business_content_publish`. The professional account must be eligible for your app’s permissions/testing mode. Paste the token into the password field. An optional app secret exchanges a short-lived token for a long-lived token; it is used for that request and not retained. Known long-lived tokens are refreshed when nearing expiry; tokens entered without an exchange have unknown expiry and may need manual reconnection. This first local version uses token entry rather than hosted Meta OAuth. See [Meta’s Instagram Login guide](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login/).
- **Temporary storage:** enter your HTTPS S3-compatible endpoint without a bucket path, bucket, region (`auto` for R2), and access/secret keys. Use a private bucket and credentials with PutObject, GetObject and DeleteObject access to Clipper’s `clipper/` prefix. Temporary AWS session credentials are not supported. “Configured” means saved; connectivity is checked during upload. Clipper does not change bucket ACLs or policies. [Instagram Login publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing/) requires Meta to fetch an HTTPS media URL; Clipper stages only the selected clip and creates a one-hour signed fetch URL.

Credentials and YouTube resumable session URLs are saved through the native OS credential store (macOS Keychain / Windows Credential Manager). Plaintext fallback is refused. If the OS store asks for access, approve it locally. **Disconnect** removes the saved account token; it does not revoke permissions at Google/Meta. Google’s client configuration remains available locally for reconnection.

Choose **Publish clip →** below a completed preview. Edit the posting title/description/caption, choose YouTube, Instagram, or both, and set visibility/audience. These fields do not change the burned-in top headline. YouTube defaults to **Private**; the audience choice has no default. **Review upload** shows the exact clip version, accounts and posting text. **Upload now** starts the transfer. Instagram publishes a Reel immediately, including to the feed; there is no draft or scheduling mode. YouTube may keep processing the video after transfer completes.

Upload history records each platform separately and provides post links and **Review & resume**. An identical file is uploaded at most once per saved destination account. Resumes use frozen reviewed bytes and saved posting details, even after a later headline edit. A changed file is a new version and can create a new post. If YouTube’s resumable session expires or a provider cannot confirm publication, check the account before attempting a fresh upload; Clipper refuses to create a possible duplicate automatically. If an Instagram publish is confirmed without a post ID, history links to the account instead of inventing a Reel link.

After publication Clipper deletes its own staged Instagram object. If deletion fails, history keeps the successful publication and offers **Retry cleanup**, which does not publish again. Interrupted/failed uploads can leave a staged object until resumed; use a bucket lifecycle rule if you also want provider-side expiry. The signed URL expiring does **not** delete the object. Existing unrelated bucket objects are never deleted.

Public connection metadata and upload receipts are stored in ignored `.local/publishing.sqlite3`. Frozen reviewed clips and Instagram upload copies remain in `.local/publish_media/` for retries; budget disk space for those copies. There is no automatic local cleanup yet. Keep this state if you want duplicate protection/history. No uploads start automatically after rendering, connection, or app restart. The full source replay is never sent by the publishing flow.

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

The dashboard, pipeline and publishing protocol checks have passed 163 tests and 22 subtests locally and on Windows CI, with no skips. See the [implementation and validation evidence](IMPLEMENTATION_REPORT.md) for Windows run links, output locations and limits. Desktop Safari and responsive layouts were manually checked on this Mac; Windows desktop browser/launcher interaction remains unverified. Provider protocol tests use fake credentials and HTTP responses; live publication requires connecting your accounts.

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

The `.github/workflows/windows-tests.yml` installs Python 3.11, Node 24, FFmpeg, runtime dependencies and the public test model/sample on a Windows runner, then runs the full suite. It does not download user recordings or publish videos. A successful run is still required to validate Windows execution; merely adding the workflow is not evidence of a pass.

Before calling this ready for real streams, process a **user-owned, completed Fortnite replay** and manually review the generated drafts for HUD visibility, caption timing/Hindi font rendering, audible mixed audio and useful selection. Check actual files/times against the manifest, run the command again to confirm cache/clip reuse, and try an invalid/live link to verify the error. Automated synthetic tests do not establish real YouTube download compatibility, transcription accuracy, or highlight quality. Windows installation and real replay review must be checked on the target machine.

Gameplay model training, real-time capture, cloud deployment, automatic/scheduled posting and other games are outside this release.
