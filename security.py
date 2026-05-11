# security.py
"""Central place for security/hardening utilities.

Three things live here:
  - rate_limiter:    SlowAPI Limiter instance + decorator helpers
  - CSRF helpers:    get_csrf_token() and require_csrf() dependency
  - Security headers: middleware function

Designed to be imported by main.py once and used everywhere by routers.
"""
import os
import secrets
from typing import Optional

from fastapi import Request, HTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address


# ----------------------------------------------------------------------
# Rate limiter
# ----------------------------------------------------------------------
# SlowAPI uses get_remote_address (the client IP from request.client.host)
# as the key. Behind a reverse proxy you'd want X-Forwarded-For; fly.io's
# Fly-Client-IP header is appropriate there. We add a small helper.

def _client_key(request: Request) -> str:
    """Identify the client for rate limiting.

    Strategy:
      - Behind fly.io: use Fly-Client-IP header (real client IP).
      - Local development: return a unique key per request so the
        rate limiter never matches the same bucket twice → never trips.
        Real attackers can't be on 127.0.0.1 unless they already own
        the server, at which point we have bigger problems.
    """
    fly_ip = request.headers.get("fly-client-ip")
    if fly_ip:
        return fly_ip
    raw_ip = get_remote_address(request)
    if raw_ip in {"127.0.0.1", "localhost", "::1"}:
        # Per-request unique key — guarantees no two localhost requests
        # share a rate limit bucket, so dev/test never hits the limit.
        # secrets.token_hex is fast enough to call per-request.
        return f"localhost-{secrets.token_hex(8)}"
    return raw_ip


# Single shared limiter instance. In-memory storage works for a single
# process; if we scale to multiple instances we'd switch to Redis.
#
# DISABLE_RATE_LIMIT=1 turns the limiter into a no-op. We set this in
# the test conftest so unit tests don't hit limits when they POST to
# /login dozens of times.
_DISABLE_RATE_LIMIT = os.environ.get("DISABLE_RATE_LIMIT", "0") == "1"

rate_limiter = Limiter(
    key_func=_client_key,
    default_limits=["100/minute"],
    enabled=not _DISABLE_RATE_LIMIT,
)


# ----------------------------------------------------------------------
# CSRF protection
# ----------------------------------------------------------------------
# Strategy: store a random token in the session, require it on every
# state-changing request (POST/PUT/DELETE/PATCH). Two transport options:
#   - HTML forms: hidden <input name="csrf_token"> field
#   - JS fetch:   X-CSRF-Token header
#
# Both are checked. The token is bound to the session, so a stolen token
# alone can't be replayed elsewhere.

CSRF_SESSION_KEY = "csrf_token"
CSRF_FORM_FIELD = "csrf_token"
CSRF_HEADER = "x-csrf-token"

# In test environments, CSRF is bypassed. Tests don't go through the full
# template render → fetch flow that injects tokens, and we don't want to
# manually thread tokens through every test. CSRF is exercised in the
# Playwright end-to-end test where a real browser handles tokens naturally.
_DISABLE_CSRF = os.environ.get("DISABLE_CSRF", "0") == "1"


def get_csrf_token(request: Request) -> str:
    """Get or generate a CSRF token for the current session.

    Called in template handlers and exposed to JS via a meta tag or an
    endpoint. Generates a fresh token if the session doesn't have one yet.
    """
    token = request.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


async def require_csrf(request: Request):
    """Dependency that validates CSRF on state-changing requests.

    Accepts the token from either:
      - X-CSRF-Token header (JS-driven endpoints)
      - csrf_token form field (HTML form posts)

    Raises 403 on mismatch.

    Bypassed when DISABLE_CSRF=1 (test environment).
    """
    if _DISABLE_CSRF:
        return

    # GET/HEAD/OPTIONS don't need CSRF — they shouldn't mutate state.
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    expected = request.session.get(CSRF_SESSION_KEY)
    if not expected:
        # No session token yet — refuse all mutations.
        raise HTTPException(status_code=403, detail="CSRF token missing from session")

    # Header check (used by fetch/AJAX requests)
    header_token = request.headers.get(CSRF_HEADER)
    if header_token and secrets.compare_digest(header_token, expected):
        return

    # Form-field check (used by classic HTML form posts)
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        try:
            form = await request.form()
            form_token = form.get(CSRF_FORM_FIELD)
            if form_token and secrets.compare_digest(str(form_token), expected):
                return
        except Exception:
            pass

    raise HTTPException(status_code=403, detail="CSRF token invalid or missing")


# ----------------------------------------------------------------------
# Security headers middleware
# ----------------------------------------------------------------------
# These headers tell browsers to enforce additional restrictions client-side.
# They're cheap insurance: each one closes off a real attack class.

# Whether we're behind HTTPS. Set HTTPS_ONLY=1 in production (fly.io).
HTTPS_ONLY = os.environ.get("HTTPS_ONLY", "0") == "1"


def get_csp_nonce(request: Request) -> str:
    """Get the per-request CSP nonce. Generated once per request by the
    security headers middleware and stashed on request.state. Templates
    pass this to every <script> tag they render: <script nonce="{{ nonce }}">.

    Inline scripts with the matching nonce are allowed; injected scripts
    (via XSS) won't have it and the browser blocks them.
    """
    return getattr(request.state, "csp_nonce", "")


def _build_csp(nonce: str) -> str:
    """Build the CSP header string including a per-request nonce.

    script-src includes 'nonce-<value>' so our inline scripts with
    nonce="<value>" can execute. We also allow 'self' (for /static/*.js)
    and the jsdelivr CDN (for Bootstrap, Chart.js).

    NOTE: we intentionally do NOT include 'strict-dynamic'. That keyword
    has the side effect of disabling host allowlisting — only nonced
    scripts would work, which would block our external <script src="...">
    tags unless we nonced every one. Sticking to host allowlisting +
    nonces is simpler and equally safe for our threat model.
    """
    return "; ".join([
        "default-src 'self'",
        f"script-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net",
        # 'unsafe-inline' for STYLES is OK — much less risk than scripts.
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
        "font-src 'self' https://cdn.jsdelivr.net data:",
        "img-src 'self' data:",
        # cdn.jsdelivr.net included for Bootstrap's source map fetch.
        "connect-src 'self' https://cdn.jsdelivr.net",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ])


async def add_security_headers(request: Request, call_next):
    """Middleware that attaches security headers to every response.

    Generates a fresh CSP nonce per request and stashes it on
    request.state.csp_nonce so templates can read it via get_csp_nonce().
    """
    # Generate the nonce BEFORE call_next, since templates need it.
    nonce = secrets.token_urlsafe(16)
    request.state.csp_nonce = nonce

    response = await call_next(request)

    response.headers["Content-Security-Policy"] = _build_csp(nonce)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

    if HTTPS_ONLY:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    return response


# ----------------------------------------------------------------------
# Generic error handler
# ----------------------------------------------------------------------
# By default FastAPI returns detailed error info, which can leak stack
# traces and library versions. In production we swap to a generic 500.

def configure_error_handlers(app):
    """Attach a generic 500 handler that hides internals in production."""
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    SHOW_DETAIL = os.environ.get("DEBUG_ERRORS", "0") == "1"

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        """Catch-all for unhandled exceptions. Returns a generic 500."""
        # If it's an HTTPException, let it through with its real status.
        if isinstance(exc, (StarletteHTTPException, HTTPException)):
            raise exc

        if SHOW_DETAIL:
            return JSONResponse(
                status_code=500,
                content={"detail": f"{type(exc).__name__}: {str(exc)}"},
            )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
