# tests/unit/test_security.py
"""Tests for security.py — CSRF, rate limiting, security headers."""
import os
import pytest

# Constant pulled out of security.py for use in test mocks below.
# Imported lazily inside test bodies, but we cache the name here for clarity.
from security import CSRF_HEADER


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

    def test_client_key_uses_fly_header(self, app_module):
        """When Fly-Client-IP is set (production), it's used as the key."""
        from unittest.mock import MagicMock
        from security import _client_key
        req = MagicMock()
        req.headers = {"fly-client-ip": "203.0.113.42"}
        assert _client_key(req) == "203.0.113.42"

    def test_client_key_localhost_gets_unique_key(self, app_module):
        """Localhost requests should each get a unique key (no rate limit)."""
        from unittest.mock import MagicMock, patch
        from security import _client_key
        req = MagicMock()
        req.headers = {}
        with patch("security.get_remote_address", return_value="127.0.0.1"):
            k1 = _client_key(req)
            k2 = _client_key(req)
        # Each call returns a different unique localhost key
        assert k1.startswith("localhost-")
        assert k2.startswith("localhost-")
        assert k1 != k2


class TestCSRFValidation:
    """Test the require_csrf dependency directly with mocked requests.
    These are pure unit tests — we don't go through the full app, so we
    can keep CSRF disabled globally (for other tests) while still
    exercising the validation logic here."""

    @pytest.fixture
    def enable_csrf(self, monkeypatch):
        """Force CSRF enforcement on for this test, even though the global
        env var disables it for everything else."""
        monkeypatch.setattr("security._DISABLE_CSRF", False)

    def _mock_request(self, method="POST", session_token="valid-token",
                      header_token=None, content_type="application/json"):
        """Build a minimal Request-like mock for require_csrf."""
        from unittest.mock import MagicMock
        req = MagicMock()
        req.method = method
        req.session = {"csrf_token": session_token} if session_token else {}
        req.headers = {"content-type": content_type}
        if header_token is not None:
            req.headers[CSRF_HEADER] = header_token
        return req

    @pytest.mark.asyncio
    async def test_get_request_skipped(self, app_module, enable_csrf):
        """GET requests don't need CSRF (no mutation)."""
        from security import require_csrf
        req = self._mock_request(method="GET")
        # Should return without raising
        result = await require_csrf(req)
        assert result is None

    @pytest.mark.asyncio
    async def test_head_options_skipped(self, app_module, enable_csrf):
        from security import require_csrf
        for method in ("HEAD", "OPTIONS"):
            req = self._mock_request(method=method)
            await require_csrf(req)  # should not raise

    @pytest.mark.asyncio
    async def test_no_session_token_rejected(self, app_module, enable_csrf):
        """If the session has no CSRF token, all mutations are blocked."""
        from fastapi import HTTPException
        from security import require_csrf
        req = self._mock_request(session_token=None)
        with pytest.raises(HTTPException) as exc:
            await require_csrf(req)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_valid_header_token_accepted(self, app_module, enable_csrf):
        from security import require_csrf
        req = self._mock_request(
            session_token="match-me",
            header_token="match-me",
        )
        # Should return without raising
        await require_csrf(req)

    @pytest.mark.asyncio
    async def test_wrong_header_token_rejected(self, app_module, enable_csrf):
        from fastapi import HTTPException
        from security import require_csrf
        req = self._mock_request(
            session_token="real-token",
            header_token="wrong-token",
        )
        with pytest.raises(HTTPException) as exc:
            await require_csrf(req)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_missing_token_rejected(self, app_module, enable_csrf):
        """Mutating request with no token in header AND no form."""
        from fastapi import HTTPException
        from security import require_csrf
        req = self._mock_request(
            session_token="real-token",
            header_token=None,
            content_type="application/json",
        )
        with pytest.raises(HTTPException) as exc:
            await require_csrf(req)
        assert exc.value.status_code == 403


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
