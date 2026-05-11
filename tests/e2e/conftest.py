# tests/e2e/conftest.py
"""Pytest fixtures for end-to-end Playwright tests.

USAGE:
  1. Wipe the DB and start the server in one terminal:
        # PowerShell:
        Remove-Item cafesync.db -Force -ErrorAction SilentlyContinue
        uvicorn main:app
        # Bash:
        rm -f cafesync.db && uvicorn main:app

  2. Run the tests in another terminal:
        pytest tests/e2e/ --headed --slowmo=300   # watch it
        pytest tests/e2e/                          # headless

CREDENTIALS:
  This file auto-loads your .env so the test uses the same admin
  username/password your server is using. You don't need to set
  anything separately. If your .env says ADMIN_USERNAME=admin and
  ADMIN_PASSWORD=admin, that's what the test will try.

  You can override either with shell env vars:
        $env:ADMIN_USERNAME = "different"; pytest tests/e2e/
"""
import os
from pathlib import Path

import pytest

# Load the project's .env so admin credentials match the running server.
# python-dotenv is already a project dependency.
#
# override=True is critical: pytest's project-root conftest may have set
# ADMIN_USERNAME / ADMIN_PASSWORD to test values for unit-test runs, and
# we need the REAL .env values to win for e2e tests. Without override,
# os.environ.setdefault() in the parent conftest would leave the test
# values in place and we'd try to log in with bogus credentials.
try:
    from dotenv import load_dotenv
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    load_dotenv(PROJECT_ROOT / ".env", override=True)
except ImportError:
    pass


@pytest.fixture(scope="session")
def base_url():
    """The URL of a running uvicorn server. WebAuthn requires `localhost`,
    not `127.0.0.1` — see Firefox/WebAuthn docs."""
    return os.environ.get("CAFESYNC_BASE_URL", "http://localhost:8000")


@pytest.fixture(scope="session")
def admin_credentials():
    """Reads ADMIN_USERNAME and ADMIN_PASSWORD from .env (auto-loaded above)
    or from shell env. Fails loudly if they're missing rather than silently
    falling back to placeholders that would cause confusing test failures."""
    username = os.environ.get("ADMIN_USERNAME")
    password = os.environ.get("ADMIN_PASSWORD")
    if not username or not password:
        pytest.fail(
            "ADMIN_USERNAME / ADMIN_PASSWORD not found. "
            "Make sure your .env file exists at the project root and "
            "contains both variables (these are the same ones uvicorn uses)."
        )
    return {"username": username, "password": password}


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Browser context tweaks: ignore HTTPS errors on localhost, decent viewport."""
    return {
        **browser_context_args,
        "ignore_https_errors": True,
        "viewport": {"width": 1280, "height": 800},
    }
