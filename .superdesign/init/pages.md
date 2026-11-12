# Pages

## / — Local dashboard
Entry: web/index.html
Dependencies:
- web/app.css — all styling and tokens
- web/app.js — API requests, polling, native clip template rendering, headline editing
No local imports from CSS/JS. No package.json, build system, React or component framework. Backend app.py serves this page and media; clipper.py and edit_clip.py run as subprocesses. New target: publishing-panel, extending this dashboard visual system.
