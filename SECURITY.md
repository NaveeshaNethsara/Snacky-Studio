# Security Policy

## Supported Versions

Snacky Studio maintains security patches for the following major versions:

| Version | Supported          |
| ------- | ------------------ |
| 3.x     | :white_check_mark: |
| < 3.0   | :x:                |

## Security Architecture & Controls

### Authentication & Secrets
- **Password Hashing:** Passwords in Cloud Mode are verified using **Argon2id** (RFC 9106) with tuned parameters ($m=65536\text{ KB}$, $t=3$, $p=4$, 32-byte hash length). Plaintext passwords or unsalted hashes are strictly rejected in enterprise production environments.
- **Session Management:** Sessions are tracked using HMAC-SHA256 signed opaque tokens backed by Redis server-side state. Logging out immediately revokes the token in Redis. A global session revocation mechanism (`/api/session/logout-all`) allows users to invalidate all active sessions immediately.
- **Secrets Management:** Secrets and keys are strictly injected through environment variables or secret stores at container initialization. Secrets are never hardcoded in images, git history, or application logs.

### Network & Transport Security
- **Reverse Proxy Headers & IP Spoofing Prevention:** The gateway parses `X-Forwarded-For` using RFC 7239 right-to-left traversal against a configurable subnet allowlist (`SNACKY_TRUSTED_PROXIES`). Untrusted peers cannot spoof IP addresses or trigger distributed rate-limiting lockouts.
- **HTTP Security Headers:**
  - `Content-Security-Policy`: Strict policy restricting script execution, style sources, and disabling object/frame embedding.
  - `Strict-Transport-Security`: `max-age=31536000; includeSubDomains` enforced on HTTPS.
  - `X-Frame-Options`: `DENY` (clickjacking mitigation).
  - `X-Content-Type-Options`: `nosniff` (MIME-sniffing mitigation).
  - `Referrer-Policy`: `strict-origin-when-cross-origin`.
  - `Permissions-Policy`: `camera=(), microphone=(), geolocation=(), payment=()`.
  - `Cross-Origin-Opener-Policy`: `same-origin`.

### Input Validation & SSRF Prevention
- Strict Pydantic v2 schemas reject private, loopback, or non-global IP addresses in user-submitted URLs.
- In Cloud Mode, domains are restricted to authorized social media platforms (`youtube.com`, `instagram.com`, `tiktok.com`, `facebook.com`, `twitter.com`, `x.com`).
- Filesystem writes are guarded by strict path validation (`resolve_media_file`) preventing directory traversal, path components, non-media extensions, and symlink escapes.

## Reporting a Vulnerability

If you discover a security vulnerability within Snacky Studio, please submit a private report to our security engineering team rather than creating a public issue.

- **Email:** `security@snackystudio.internal` (or repository security advisory)
- Please include:
  1. Description of the vulnerability and attack vector.
  2. Proof of concept (PoC) or reproducible steps.
  3. Potential impact and affected components.

We will acknowledge receipt within 24 hours, provide regular progress updates, and coordinate disclosure following remediation.

