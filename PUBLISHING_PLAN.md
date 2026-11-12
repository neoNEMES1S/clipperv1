# Publishing pipeline — implementation scope

Status: approved publishing flow implemented and pushed. Local and Windows checks passed (163 tests and 22 subtests, no skips). Accounts still need to be connected locally before a live upload.

Other games are deferred. The existing Fortnite extraction, local review and headline editor remain available.

## Confirmed destinations and setup

- YouTube: `@neonemesis8055`.
- Instagram: `@tyler1butsane`, a professional account using **Instagram Login**.
- The user already has Google Cloud OAuth credentials, a Meta developer app, and an S3/R2-compatible bucket.
- Credentials must be entered/imported through the local app, not chat, source control, logs or design context.

## First publishing workflow

Choose one completed clip, edit YouTube title/description and Instagram caption, choose destinations, set YouTube visibility and audience, review the exact clip/accounts/details, then upload. YouTube starts with Private selected. Instagram's publishing API creates a live Reel; the review must make that clear. Extraction and account connection never trigger publishing automatically.

Keep independent results for each destination. A successful YouTube upload must remain recorded if Instagram fails, and vice versa. Save remote IDs, links and processing stages. Detect an existing upload for the same clip content and destination account. Resume known upload sessions; do not blindly create another post after an uncertain final response. Keep the current one-job-at-a-time behavior.

## Integration approach

**YouTube:** installed-app OAuth with a loopback callback and PKCE, using the official Google OAuth library. Verify that the authenticated YouTube channel matches the selected handle. Request upload plus channel-read access for that identity check. Upload with Google's documented resumable protocol, saving the session securely and honoring returned byte ranges before resuming. Save the video ID as soon as the upload is acknowledged. Treat uploaded/private/processing/published as different states.

**Instagram:** use the user's Instagram Login setup and its account access token. Verify the username before storing the connection. Use an app-generated token through the local setup form; a hosted OAuth redirect is outside this first local-only setup. Provide expiry/reconnection guidance and support the platform's token refresh where applicable. Create a REELS media container from a temporary signed HTTPS URL, poll until FINISHED, then call media_publish. Persist the container ID before publishing, reconcile uncertain outcomes, and save the final media ID/permalink when returned.

**Temporary media:** use the existing private S3-compatible bucket. Upload only the reviewed clip under an unguessable object key, generate an expiring presigned GET URL for Meta, and delete the staged object after ingestion. A cleanup failure remains visible and retryable. Do not change bucket ACLs, make the local dashboard public, or upload an entire replay. Normalize Instagram's upload copy if needed while preserving the original local clip.

**Secrets:** OS credential storage, with no plaintext fallback for account tokens, refresh tokens, client credentials, storage keys or sensitive upload-session URLs. Keep non-secret upload records separately in an ignored local state directory. Secrets never appear in API snapshots, error text, posting notes or browser storage.

## Trust boundaries and checks

Restrict publishing to completed, manifest-listed MP4s. Validate media and metadata limits before starting. Bind the review to the file's identity/hash, platform accounts and immutable posting details; recheck before upload. Keep localhost host/origin/token protections on all write endpoints. Use bounded-memory transfers and avoid automatic publishing after restarting the app.

Test account mismatches, OAuth state/PKCE, secret redaction, invalid paths, changed clips after review, resumable byte offsets, duplicate submissions, partial platform success, Instagram processing/errors, ambiguous publish replies, cleanup and restart recovery. Use mocked provider boundaries plus native media/HTTP checks. Live uploads still require the user's local account connection and a concrete reviewed clip.

Scheduling, bulk automatic posting, analytics and other-game detectors are outside this change.

## Validation and remaining live check

Implemented in `publish_accounts.py`, `publishing.py`, `publish_uploads.py`, the loopback HTTP endpoints and the existing browser interface. Native Safari checked the composer, required audience choice, exact review text/accounts/version and a 390×844 account layout using isolated test connections; that test server refused all upload/account mutations. The real workspace still has no connected accounts or upload receipts. None of the 11 saved clips were modified or posted by these checks.

Local: 163 tests and 22 subtests passed in 10.55 seconds, including real FFmpeg Instagram normalization with unchanged video packets/original file. Windows: the same counts passed in 27.36 seconds in [run 43211815872](https://github.com/neoNEMES1S/clipperv1/actions/runs/43211815872), source commit `776ab847df5ccb56c88d9d6fa53ad60fedd05b7e`. Both had no skips; dependency checks passed.

Still pending: import/connect the user's actual credentials in the local UI, choose a specific clip and posting details, and perform the first reviewed upload. API protocol tests use fake provider responses and do not establish live account permissions, storage reachability, Keychain authorization or publication success. Windows browser/launcher interaction is also unverified. Frozen upload copies remain on disk for resuming; there is no automatic local garbage collection.

## Primary references

- [Google installed-app OAuth](https://developers.google.com/identity/protocols/oauth2/native-app)
- [YouTube resumable uploads](https://developers.google.com/youtube/data/guides/using_resumable_upload_protocol)
- [YouTube videos.insert](https://developers.google.com/youtube/data/reference/rest/v3/videos/insert)
- [Meta content publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing/)
- [Meta's Reels publishing sample](https://github.com/fbsamples/reels_publishing_apis/blob/main/insta_reels_publishing_api_sample/README.md)

The Meta publishing documentation was retrieved directly during research. Its current requirements distinguish `graph.instagram.com` for Instagram Login from Facebook Login's `rupload.facebook.com` file-upload flow. Instagram Login therefore needs a fetchable media URL; the existing private bucket and expiring signed links satisfy that without exposing the dashboard.
