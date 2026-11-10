# Migration validation — 10 October 2026

Verified on Windows with Python 3.14.5, Node 24.14.0 and an isolated Chrome test profile.

| Check | Result |
| --- | --- |
| Production React/TypeScript/Vite build | Passed |
| Pytest backend suite | 72 passed, 15 subtests passed |
| Real cloud infrastructure tests | 2 skipped; PostgreSQL/Redis/S3 containers unavailable here |
| Vitest | 7 passed |
| Playwright | 3 passed |
| Previous frontend compatibility suite | 12 passed |
| Real MP4 and 320 kbps MP3 conversion | Passed, generated localhost clip |
| Original photos / ZIP / PNG conversion | Passed, original bytes and decoded pixels checked |
| Music slideshow | Passed, photo order, dimensions, duration and original audio checked |
| Frozen desktop backend | Passed offline startup, bundled runtimes, React assets, Unicode/range attachments, isolated gallery-dl dispatch, graceful child shutdown and temporary cleanup |
| Docker Compose manifest | Passed official schema validation; all referenced image tags exist |
| PostgreSQL migration | Generated valid offline upgrade SQL |
| Existing local video | Completed; v3 serves its attachment with byte ranges |
| Launcher | Reuses the running v3 preview on port 8126 |

The browser download test prepares two jobs simultaneously, reloads the page, then verifies both native download files byte-for-byte against their completed attachments and checks their Unicode names. The other browser tests cover mobile Facebook photo controls/retry and mocked private-workspace sign-in/error/sign-out UI. Backend tests separately exercise actual session enforcement and shared rate limits.

Default cloud contract tests use isolated SQLite repositories, fake Redis and Moto's S3 emulator. They verify admission across repositories, failed dispatch retry, redelivery, ownership fencing, cancellation, publication, missing-worker-disk delivery and access controls. They do not constitute a real PostgreSQL/Celery deployment test.

Docker is unavailable on this machine. Cloud integration and assembled deployment workflows are provided, but have not run remotely. The Tauri CLI detects WebView2 and reports missing Rust/Cargo and required MSVC/SDK components. The frozen Python/Node backend is built and tested; the Rust shell and Windows installer remain uncompiled here.

The app is running at **http://127.0.0.1:8126/**. The original server was preserved throughout the migration and its video finished successfully. Existing files and local task records remain available.

Screenshot evidence:

- `scratch/snacky-studio-v3.jpg`: final application with the existing library.
- `scratch/react-downloads-verified.png`: concurrent completed browser downloads.
- `scratch/react-mobile-verified.png`: responsive Facebook photo controls.
- `scratch/react-private-login-verified.png`: private workspace login UI.

Pre-migration source: `scratch/before-scalable-stack/`. Setup and deployment commands: `README.md`.
