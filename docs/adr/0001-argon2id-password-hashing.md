# ADR-001: Password Hashing with Argon2id

## Status
Accepted

## Context
In the original implementation of Snacky Studio cloud mode, password verification was performed using:
```python
hmac.compare_digest(hashlib.sha256(body.password.encode()).digest(), hashlib.sha256(settings.cloud_password.encode()).digest())
```
SHA-256 is an unsalted cryptographic digest that provides no memory or time resistance against modern GPU/ASIC brute-force cracking. If the hash or source was compromised, passwords could be cracked at billions of computations per second.

Furthermore, client IP extraction naively inspected `request.client.host`, which caused all requests behind Nginx reverse proxy to share the gateway's internal IP, leading to global workspace lockouts upon 10 failed login attempts.

## Decision
1. **Adopt Argon2id** (RFC 9106) via `argon2-cffi` as the primary password verification engine.
2. **Parameters:**
   - Type: `Argon2id` (hybrid of Argon2i and Argon2d, providing resistance against side-channel and GPU cracking attacks).
   - Memory cost ($m$): $65,536\text{ KB}$ (64 MB).
   - Time cost ($t$): 3 iterations.
   - Parallelism ($p$): 4 threads.
   - Hash length: 32 bytes.
3. **Transparent Compatibility:**
   - Support `SNACKY_CLOUD_PASSWORD_HASH` for pre-hashed Argon2id credentials.
   - Retain backward compatibility with legacy `SNACKY_CLOUD_PASSWORD`, verifying via constant-time comparison.
4. **Proxy-Aware Client IP Extraction:**
   - Implement RFC 7239 compliant right-to-left traversal of `X-Forwarded-For`.
   - Only trust forward headers if the direct socket peer is in configured `SNACKY_TRUSTED_PROXIES` networks.
5. **Server-Side Session Revocation:**
   - Back sessions with Redis key `snacky:session:{nonce}` and revocation set `snacky:revoked:{nonce}`.
   - Support `POST /api/session/logout-all` to invalidate all active sessions via `snacky:revoked_before`.

## Consequences
### Positive
- Enterprise-grade protection against offline password cracking.
- Prevents Denial of Service via IP rate-limiting behind reverse proxies.
- Immediate revocation of leaked or stolen session tokens.
- Fully compatible with zero-config local desktop mode.

### Negative
- Minor CPU/memory overhead per login attempt (~40-60ms, 64MB memory during computation), which is desirable for rate-limiting brute force.
- Adds `argon2-cffi` dependency to `requirements-cloud.txt`.

