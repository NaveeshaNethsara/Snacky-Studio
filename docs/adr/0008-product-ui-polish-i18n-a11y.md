# ADR 0008: Product & UI Polish (Batch Processing, User Preferences, i18n, and Automated a11y)

- **Status:** Accepted
- **Date:** 2026-11-09
- **Author:** Principal Software Engineer & Systems Architect

## Context
Following the stabilization and scalability optimizations in Phases 1–7, Snacky Studio required enterprise-grade UX polish, localization, batch workflow efficiency, and automated accessibility compliance:
1. **Batch Media Workflows:** Users and business integrations frequently need to download multiple media items simultaneously rather than pasting URLs one by one. Without aggregate batch tracking, monitoring multiple concurrent downloads requires tracking disjoint task IDs.
2. **User Preferences & Personalization:** Power users need persistent defaults for preferred video resolutions (e.g. 1080p, 720p), audio bitrates (e.g. 320 kbps), dark/light themes, and automatic download triggers across sessions.
3. **Multi-Language Accessibility (i18n):** To serve global enterprise workspaces, the UI must support seamless multi-language switching (English and Spanish base) with a zero-runtime-overhead translation framework.
4. **Media Library Organization:** As media libraries grow to hundreds of files, users require fast client-side searching, media type filtering (video, audio, photos), and multi-field sorting (date, size, name).
5. **Accessibility (a11y) Standards:** Enterprise software must meet WCAG 2.1 AA accessibility guidelines (semantic HTML, proper ARIA attributes, keyboard navigation, focus management, screen-reader support).

## Decisions

### 1. Batch URL Processing Architecture
- Implemented `POST /api/batch` and `POST /api/v1/batch` accepting up to 50 URLs or structured `BatchItem` payloads with individualized format and quality parameters.
- Assigned unique `batch_id` identifiers to group tasks while preserving individual task progress, cancellation, and download lifecycle states.
- Implemented `GET /api/batch/{batch_id}` and `GET /api/v1/batch/{batch_id}` returning aggregate progress (completed, in-progress, queued, failed) alongside detailed task snapshots.
- Created `BatchDownloader.tsx` component in the React UI with multi-line input, URL count detection, format/quality controls, and real-time batch progress indicators.

### 2. User Preferences Persistence & Caching
- Added `user_preferences` table via Alembic migration `0007_user_preferences.py`:
  - `user_id`: VARCHAR(36) PK
  - `tenant_id`: VARCHAR(36) FK
  - `preferences`: JSON (default_format, default_quality, default_audio_bitrate, theme, language, auto_download)
  - `updated_at`: FLOAT
- Added Redis caching layer (`snacky:cache:pref:{user_id}`) with 300s TTL and immediate write-invalidation.
- Implemented local desktop fallback storing preferences in `.snacky/preferences.json`, preserving the lightweight zero-config guarantee.
- Added accessible `PreferencesModal.tsx` dialog for configuring appearance, language, and download defaults.

### 3. Lightweight i18n Framework
- Implemented `frontend/src/lib/i18n.ts` with complete English (`en`) and Spanish (`es`) dictionaries covering 100% of the UI (headings, forms, buttons, task statuses, library controls, error notices).
- Provided `I18nProvider` context and `useTranslation()` hook with dynamic parameter interpolation (`t(key, { count, size })`).
- Persisted selected language to `localStorage` and synchronized with user preferences and `document.documentElement.lang`.
- Added header language switcher button (`EN` / `ES`).

### 4. Library Search, Filter, and Multi-Field Sorting
- Enhanced `Library.tsx` with:
  - Real-time search across titles, filenames, and media formats.
  - Media type filters: All, Videos, Audio, Photos.
  - Multi-field sort controls: Date (newest/oldest), Size (largest/smallest), Name (A-Z/Z-A).
  - Ascending/descending sort direction toggle.

### 5. Automated Accessibility Audits in CI (axe-core / Playwright)
- Integrated `axe-core` and `@axe-core/playwright` for automated WCAG 2.1 AA audits.
- Implemented `frontend/src/test/a11y.test.tsx` verifying zero critical or serious accessibility violations across `BatchDownloader`, `Library`, and `PreferencesModal`.
- Added Playwright E2E accessibility suite `frontend/e2e/a11y.spec.ts` testing the entire live DOM, ARIA roles, labels, and dialog focus traps.
- Added `npm run test:a11y` command to `frontend/package.json`.

## Alternatives Considered
- **Heavy i18n Libraries (react-i18next):**
  - *Alternative:* Install `i18next` and `react-i18next`.
  - *Why Rejected:* Added 50+ kB of bundle overhead and third-party dependencies for standard key-value translations. Our typed dictionary context provides sub-microsecond translation lookups with zero external bundle bloat.
- **Client-Only Preferences in localStorage:**
  - *Alternative:* Store preferences purely in browser `localStorage`.
  - *Why Rejected:* Multi-device enterprise users lose their preferences when moving between desktop, tablet, or web sessions. Storing in the database with Redis caching guarantees cross-device consistency while localStorage serves as offline fallback.

