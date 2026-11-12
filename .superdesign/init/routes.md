# Routes

Python standard-library ThreadingHTTPServer in app.py, no frontend router. GET / renders web/index.html. GET /app.css and /app.js serve exactly those assets. GET /api/state supplies job and run data. GET /media/<run>/<clip> serves a completed manifest-listed MP4 with byte ranges. POST endpoints start processing, edit a headline, and open the output folder. The new publishing feature does not exist yet.
