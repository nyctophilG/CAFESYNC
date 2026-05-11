# CafeSync — Security Audit

This document inventories the hardening measures in place. Each entry pairs
a concrete threat with the specific code that mitigates it.

## Threat model

The relevant attacker has tools like `curl`, `httpx`, a browser, and basic
familiarity with web exploits (CSRF demo pages, simple brute-force scripts).
We are not targeting protection against a determined APT — we aim for
defense-in-depth against opportunistic attacks.

## Mitigations

### 1. Credential brute-force → Rate limiting
**Threat.** Attacker scripts thousands of `POST /login` requests trying
common passwords on the `admin` account.

**Mitigation.** SlowAPI rate limiter (`security.py`):
- `POST /login`: 5 / minute / IP
- `POST /signup`: 3 / minute / IP
- `POST /2fa/confirm`: 5 / minute / IP
- `POST /login/2fa`: 5 / minute / IP

429 response includes generic "Too many requests" — no info disclosure about
which limit triggered. Behind fly.io's edge, `Fly-Client-IP` header is
respected so a single attacker can't bypass via X-Forwarded-For spoofing.

### 2. Cross-Site Request Forgery → CSRF tokens
**Threat.** Attacker tricks logged-in admin into clicking a link that
triggers `DELETE /users/1` or `PUT /users/N/role`. Browser sends the
admin's session cookie automatically; server doesn't know the request
came from a malicious page.

**Mitigation.** Per-session CSRF token (`security.require_csrf`):
- Random 256-bit token stored in the session at first page render.
- Injected into pages as `<meta name="csrf-token">`.
- All JS `fetch` calls auto-include it as `X-CSRF-Token` header.
- Server-side dependency on `/orders/*` and `/users/*` routers rejects
  any state-changing request without a matching token (403).
- `secrets.compare_digest` used for constant-time comparison.

### 3. Session hijacking → Hardened cookies
**Threat.** Attacker on the same Wi-Fi sniffs the session cookie over HTTP,
replays it to impersonate admin.

**Mitigation.** `SessionMiddleware` config in `main.py`:
- `https_only=True` in production (gated by `HTTPS_ONLY=1` env var)
- `same_site="strict"` in production — cookies never sent on cross-site
  requests, defeats most cross-origin attacks
- Cookies signed with `SESSION_SECRET` via `itsdangerous` — tampering
  invalidates the cookie

### 4. XSS → Content Security Policy + output escaping
**Threat.** Attacker injects `<script>` via an order item name; admin's
dashboard executes it.

**Mitigations.**
- **CSP header** (`security.CSP_DIRECTIVES`): `script-src 'self'
  https://cdn.jsdelivr.net` — inline scripts and arbitrary external
  scripts are blocked by the browser even if injection succeeds.
- **Output escaping**: all user content rendered in JS goes through
  `escapeHtml()` (e.g. `app.js:escapeHtml`); template variables go
  through Jinja2's auto-escape.
- **`X-Content-Type-Options: nosniff`**: prevents the browser from
  treating a JSON response as HTML.

### 5. Clickjacking → frame-ancestors
**Threat.** Attacker wraps our admin page in an invisible iframe on
their site and tricks admin into clicking buttons that route to
state changes.

**Mitigation.** `X-Frame-Options: DENY` + CSP `frame-ancestors 'none'`.
The browser refuses to render our pages inside any frame.

### 6. HTTPS downgrade → HSTS
**Threat.** Attacker performs a MITM on first visit, serves the site
over HTTP, captures cookies.

**Mitigation.** `Strict-Transport-Security: max-age=31536000;
includeSubDomains` header in production. After first visit, browsers
refuse HTTP for the domain for a year.

### 7. Error info disclosure → Generic 500 handler
**Threat.** Unhandled exception leaks stack trace including file paths,
library versions, internal logic.

**Mitigation.** `security.configure_error_handlers` registers a
catch-all that returns `{"detail": "Internal server error"}` in
production (gated by `DEBUG_ERRORS=1` for local debugging).

### 8. Username enumeration via timing → dummy hash
**Threat.** Attacker measures response time of `POST /login`. If the
server skips bcrypt for unknown usernames, valid-but-wrong-password
takes much longer than unknown-username. Attacker enumerates valid
usernames.

**Mitigation.** `auth_utils.authenticate_user` runs a dummy bcrypt
comparison when the user doesn't exist, equalizing timing.

### 9. Password length attack → bcrypt 72-byte enforcement
**Threat.** bcrypt silently truncates input >72 bytes. An attacker
who sets a password like `"correctpassword" + "a"*100` could log in
with just `"correctpassword"` after truncation, sometimes.

**Mitigation.** `auth_utils.hash_password` and `verify_password`
explicitly check input length and reject >72 bytes.

### 10. SQL injection → parameterized queries
**Threat.** User input in a SQL query.

**Mitigation.** SQLAlchemy ORM — all queries use parameter binding.
No raw string concatenation in any DB query. Reviewed manually.

### 11. Permission escalation → server-side role checks
**Threat.** A "viewer" user manipulates the dashboard JS to send
"Serve" requests; if the server only relied on UI hiding, this would
succeed.

**Mitigation.** Every state-changing endpoint has a server-side role
dependency (`require_admin`, `require_fulfillment`). UI hiding is a
UX layer, not a security layer.

### 12. Last-admin lockout → safeguards
**Threat.** Admin demotes themselves or deletes their own account,
locking out the system.

**Mitigation.** `routers/users.py` blocks:
- changing your own role (any direction)
- deleting your own account
- demoting/deleting the last remaining admin

## Verification

- 135 unit tests passing, 90.12% coverage
- Playwright end-to-end test exercises the full user/admin/barista/viewer
  flow, including 2FA setup, backup code login, backup code single-use
  enforcement
- All threats above are exercised by either unit or e2e tests

## Known limitations

- Rate limit storage is in-memory; resets on restart. Acceptable for
  single-instance fly.io deployment.
- No CAPTCHA — rate limit alone gates brute force.
- No password complexity rules beyond min length 8 — application is for
  graded coursework, not real customer data.
- WebAuthn passkeys cannot be tested in headless browsers, so the
  Playwright test verifies only UI presence.
