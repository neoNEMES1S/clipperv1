# Publishing panel

New feature in Clipper, matching the approved charcoal/warm-gold local utility. Keep the existing replay processing and headline editor intact. This page/panel is for reviewing and uploading one finished clip at a time. Other games are deferred.

## Destinations and connection state

User-selected targets: YouTube @neonemesis8055; Instagram @tyler1butsane (professional account, Instagram Login). They have Google Cloud OAuth credentials, a Meta app, and an S3/R2-compatible bucket. Do not imply any account is already connected.

Show a compact Publishing section with three connection cards or rows: YouTube, Instagram, Temporary media storage. Each initially says Not connected; target account names are clearly desired destinations. YouTube setup imports a Desktop OAuth client JSON locally and then opens Google's sign-in/consent page. Instagram accepts an access token generated from the user's Meta app in a password field; it never displays the saved token. Storage accepts endpoint, bucket, region, access key ID and secret access key in a collapsible configuration form. Secrets stay in the OS credential store; show only connected identity/bucket, never credential values. Include short connection guidance, not a developer console.

## Publish composer

Clip selector and a portrait native-video preview (use a blank video placeholder in the design). Source interval and filename identify exactly which clip is selected. To the right, editable YouTube title and description, Instagram caption; destination checkboxes; YouTube visibility Private / Unlisted / Public (Private selected); and the required YouTube audience choice Made for kids / Not made for kids. Keep title/headline distinct: these fields edit posting metadata, not the burned-in headline.

Review upload opens a concise final summary: clip, account names, chosen platforms, posting text, YouTube visibility. Explain that Instagram publishes the Reel to that account; temporary storage is used only for the selected clip. Upload now is the explicit final action. No upload starts after rendering or account connection. Avoid fake checkmarks, fake account connection, invented numbers, scheduled-post options, analytics, or unsupported success claims.

## Results

Show per-platform stages, errors and finished post links. Keep independent status when one destination succeeds and the other fails. An already uploaded clip is identified rather than silently uploaded twice. Resuming an interrupted attempt uses its saved details. The design should include a clearly labelled empty history, not fabricated published posts.

## Constraints

Use the existing page's fonts, palette, spacing, border and controls. No sidebar, marketing hero, new branding, remote gameplay images or fonts. Desktop two-column composer stacks on mobile. Accessible labels, keyboard controls, clear focus, minimum 44px actions. This draft is a visual review; no accounts are connected and no footage is uploaded from it.
