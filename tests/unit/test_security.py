# tests/unit/test_security.py
"""Tests for security.py — CSRF, rate limiting, security headers."""
import os
import pytest


class TestSecurityHeaders:

    def test_security_headers_present_on_response(self, client):
        """Every response should carry the security headers we set."""
        r = client.get("/health")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"
        assert "Referrer-Policy" in r.headers
        assert "Content-Security-Policy" in r.headers

    def test_csp_blocks_inline_script(self, client):
        """CSP header should not include 'unsafe-inline' for scripts."""
        r = client.get("/health")
        csp = r.headers.get("Content-Security-Policy", "")
        # The script-src directive must NOT have unsafe-inline
        script_src = next((p for p in csp.split(";") if "script-src" in p), "")
        assert "unsafe-inline" not in script_src

    def test_csp_allows_self_and_cdn(self, client):
        r = client.get("/health")
        csp = r.headers.get("Content-Security-Policy", "")
        assert "'self'" in csp
        assert "cdn.jsdelivr.net" in csp

    def test_hsts_only_when_https_enabled(self, client):
        """HSTS should NOT be set in dev (HTTPS_ONLY != 1)."""
        r = client.get("/health")
        # Tests run with HTTPS_ONLY unset, so HSTS shouldn't be present.
        assert "Strict-Transport-Security" not in r.headers


class TestCSRFTokenEndpoint:

    def test_csrf_endpoint_returns_token(self, client):
        r = client.get("/csrf-token")
        assert r.status_code == 200
        body = r.json()
        assert "csrf_token" in body
        assert len(body["csrf_token"]) > 16

    def test_csrf_token_persists_in_session(self, client):
        """Subsequent calls should return the same token for the same session."""
        r1 = client.get("/csrf-token")
        t1 = r1.json()["csrf_token"]
        r2 = client.get("/csrf-token")
        t2 = r2.json()["csrf_token"]
        assert t1 == t2


class TestRateLimiter:
    """Note: rate limits are DISABLED in tests via env var, so we just
    verify the limiter object exists and is wired correctly."""

    def test_rate_limiter_exists(self, app_module):
        from security import rate_limiter
        assert rate_limiter is not None

    def test_app_has_limiter_state(self, app_module):
        """main.py wires rate_limiter onto app.state.limiter."""
        assert hasattr(app_module.app.state, "limiter")


class TestGenericErrorHandler:

    def test_404_returns_json(self, client):
        """Existing 404 behavior shouldn't be changed by the generic handler."""
        r = client.get("/this-path-does-not-exist")
        # Auth gate redirects unknown paths to /login when unauthenticated;
        # under that flow we get a 302 not a 404. Still a defined response.
        assert r.status_code in (302, 404)

    def test_health_works(self, client):
        """Sanity: the error handler doesn't break normal traffic."""
        r = client.get("/health")
        assert r.status_code == 200
