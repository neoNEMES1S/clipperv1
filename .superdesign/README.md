# Local frontend design

Status: version 2 approved by the user; implemented as the local dashboard.

- Project: `46bc1e05-1728-4505-aa56-d4b5a0dd2fce`
- Draft: `77cd1889-d3c6-4adb-859e-bd668df154ab`
- [Preview](https://p.superdesign.dev/draft/77cd1889-d3c6-4adb-859e-bd668df154ab)
- [Canvas](https://superdesign.dev/teams/c8c2a750-c51a-4dbc-8c77-67b25fae04f9/projects/46bc1e05-1728-4505-aa56-d4b5a0dd2fce)

The design began without frontend code to initialize. Implementation lives in `app.py` and `web/`, with Mac/Windows launchers. It uses actual local MP4s, manifest data and subprocess progress, bundled CSS/JS without CDNs, a loopback server, validated job options, one active job, and access restricted to completed output clips. The remote design preview uses placeholder video areas; the local app is the functional result. The original Python CLI and output files remain available.
