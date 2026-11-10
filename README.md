# Snacky Studio

A media workspace for video, audio and photo posts. The React interface uses the logo's pink, violet and cyan colors. Paste a link, choose an output, and start another download while the file is being prepared. Completed files save through your browser's download manager.

## Stack and modes

| Layer | Technology |
| --- | --- |
| Interface | React, TypeScript, Vite |
| UI | Tailwind CSS 4, shadcn/ui, Radix, Lucide |
| API | FastAPI, Pydantic, Uvicorn |
| Media | yt-dlp, gallery-dl, bundled FFmpeg/ffprobe |
| Local persistence | SQLite |
| Cloud persistence | PostgreSQL, SQLAlchemy, Alembic |
| Cloud processing | Celery, Redis |
| Progress | SSE, serial polling fallback |
| Desktop | Tauri 2, frozen Python sidecar, bundled Node |
| Deployment | Docker Compose, Nginx, S3-compatible storage |
| Verification | Pytest, Vitest, Playwright |

**Local:** one loopback API process, two media workers and eight waiting jobs. Existing downloads and `.snacky/jobs.sqlite3` remain compatible. No Redis, PostgreSQL, Docker or cloud login is required.

**Private cloud:** one password-protected shared workspace. API and worker replicas share jobs through PostgreSQL and save files in object storage. Authorized team members share tasks and files; there are no separate user accounts. The included Compose deployment runs on one host and can scale API/worker containers. Shared data services need separate redundancy and backups for high availability.

## Start locally

The built interface is in `app/web`. Double-click `start.bat`, or run:

```powershell
.\.venv\Scripts\python.exe run.py
```

The launcher reuses a running Snacky Studio instance or selects a free port from 8000-8019. It also recognizes the migration preview on port 8126. `--no-browser` starts quietly. Keep the server running until preparation and file saving finish.

For a fresh checkout, use Python 3.14 and Node 24:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend
npm ci
npm run build
cd ..
.\.venv\Scripts\python.exe run.py
```

On Linux/macOS use `.venv/bin/python`. `static_ffmpeg.add_paths()` supplies FFmpeg; source-mode first startup may obtain its binaries over the network. YouTube extraction uses Node and the matching EJS solver installed by `yt-dlp[default]`.

For frontend development, run the API and `npm run dev` in separate terminals. Vite proxies `/api` and `/static` to `http://127.0.0.1:8000`. Set `SNACKY_API_URL` in the frontend terminal when the API uses another address.

## Download workflow

1. Paste a public video or photo-post link and choose **Continue**.
2. Choose MP4 and an available resolution, or MP3 and an encoding bitrate. Unknown resolution offers **Original**.
3. Click **Download**. The input clears, allowing another link immediately.
4. Each task shows preparation progress, speed and time remaining. Conversion finishes before the file enters Chrome Downloads, with its full size known.
5. Use **Cancel**, **Retry**, **Save when ready**, **Save again**, or **Download another**. Refreshing the initiating tab restores its pending save intentions.

Chrome may ask you to allow multiple automatic downloads for this application. Once a completed file is handed off, Chrome manages that copy. Cancellation on the page stops preparation at a media checkpoint. Transient transfer failures are retried; source availability and speed still depend on the platform. MP3 bitrate controls encoding and cannot restore missing source detail.

The library shows three recent files, with View all, search, filters, save and confirmed deletion. Local mode offers Open folder. Cloud mode downloads completed objects through short-lived signed URLs.

## Photos and slideshows

Supported photo workflows include public Facebook photos/posts, TikTok photo posts, Instagram images/carousels and YouTube community images.

- Single-photo posts without music offer **Save photo** and **Save PNG**. Original saving preserves supplied bytes; PNG conversion preserves decoded dimensions without upscaling.
- Collections offer **All photos · ZIP**, preserving every accessible image in source order plus a `post.json` manifest. A failed transfer publishes no partial archive.
- TikTok posts with an exposed soundtrack offer **Slideshow · MP4**. Images play in order, evenly spaced over the available original music. Manual swipe timings cannot be recovered. Missing music disables this option.

Facebook matching is tied to the requested photo ID, with a public-embed fallback. Extractors run in isolated subprocesses and do not automatically read personal gallery-dl configuration or browser cookies. Limits: 200 photos, 100 MB per image, 2 GB per collection and a soundtrack up to 10 minutes.

Set `SNACKY_COOKIES_FILE` to a local Netscape-format cookies file for a session you are authorized to access. Private/friends-only content requires that account's existing permission. Cloud workers need their own explicitly mounted cookies file; local browser sessions are not automatically shared with containers.

## Private cloud

Install Docker with Compose, then run from the project root:

```powershell
python scripts/create_cloud_env.py
docker compose --env-file .env.cloud up --build -d --wait
```

Open **http://localhost:8080**. Read `SNACKY_CLOUD_PASSWORD` locally in `.env.cloud` to sign in. The generator creates strong credentials without printing them and refuses to overwrite an existing file. `.env.cloud` is ignored by source control.

Compose runs PostgreSQL, Redis, RustFS (S3-compatible storage), bucket initialization, Alembic migrations, API, worker and Nginx gateway. Named volumes preserve database, queue and object data. API/object-store ports bind to loopback; database and Redis are internal. The bucket is private.

Scale APIs and processing independently:

```powershell
docker compose --env-file .env.cloud up -d --scale api=2 --scale worker=3
```

Each worker container processes two jobs. Nginx resolves API replica addresses and leaves SSE unbuffered. APIs coordinate through PostgreSQL and delegate media processing to workers. `docker compose --env-file .env.cloud down` stops services while preserving named volumes.

For remote access, put an HTTPS reverse proxy in front of the gateway, set `SNACKY_PUBLIC_ORIGIN` to its exact HTTPS origin, and configure an HTTPS `SNACKY_S3_PUBLIC_ENDPOINT` reachable by users. Internal storage addressing remains separate. Managed PostgreSQL, Redis and AWS S3 can replace the included services. AWS S3 uses the SDK credential chain; custom endpoints can be empty. Back up database and objects together, and configure lifecycle cleanup for incomplete multipart uploads.

Cloud access uses signed HttpOnly/SameSite cookies, shared login rate limits and origin checks. Source admission permits supported social-platform domains. This targets a trusted private team workspace; an anonymous public downloader requires user accounts, quotas, stronger network isolation and abuse controls.

## Windows desktop build

Tauri starts an isolated local backend in the user's application-data folder. Completed attachments open in the default browser. Python, Node and FFmpeg are included in the bundle.

Build prerequisites: Rust/Cargo, Visual Studio C++ Build Tools with the Windows SDK, and WebView2. See [Tauri's Windows prerequisites](https://v2.tauri.app/start/prerequisites/#windows).

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
cd frontend
npm ci
npm run build
cd ..
.\.venv\Scripts\python.exe scripts/build_sidecar.py
.\.venv\Scripts\python.exe -m tests.sidecar_smoke
cd frontend
npm run desktop:build
```

The installer is written to `frontend/src-tauri/target/release/bundle/nsis/`. `npm run desktop:dev` uses the built UI; use Vite in a browser for hot reload. The manual `Build Windows desktop` GitHub workflow builds/uploads an installer on a Windows runner. Signing requires a separate signing configuration.

**Current machine:** the frozen backend has been built and verified offline, including bundled runtimes and graceful shutdown. Rust/Cargo and required MSVC/SDK components are unavailable, so the Tauri shell/installer has not been compiled here. Docker is unavailable here; assembled cloud deployment and real PostgreSQL/Celery/S3 checks are configured in CI and have not been executed on this machine.

## Verify

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m tests.media_smoke
.\.venv\Scripts\python.exe -m tests.photo_smoke
cd frontend
npm test
$env:SNACKY_BROWSER_CHANNEL = 'chrome'
npm run test:e2e
```

Playwright uses an isolated browser profile and a temporary media workspace on port 8124. If Chrome is unavailable, run `npx playwright install chromium` and leave `SNACKY_BROWSER_CHANNEL` unset. Browser tests prove concurrent native saves, complete bytes, Unicode filenames, refresh recovery, retry controls and mobile photo layout. Media smoke checks use real yt-dlp/FFmpeg with generated local fixtures.

Default cloud contract tests use isolated SQLite repositories, fake Redis and Moto's S3 emulator. Two opt-in tests in `test_cloud_integration.py` use real PostgreSQL, Redis, Celery and storage when `SNACKY_INTEGRATION=1`; cloud CI supplies those services. Deployment CI builds/starts two API and two worker replicas, then checks sessions and SSE through Nginx. Creating these workflows does not mean remote jobs have run.

See [ARCHITECTURE.md](ARCHITECTURE.md) and [VALIDATION.md](VALIDATION.md). Pre-migration source is backed up in `scratch/before-scalable-stack/`. The previous UI remains at `/legacy` for transition checks.
