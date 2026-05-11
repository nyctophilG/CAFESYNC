# conftest.py (project root)
"""Pytest fixtures shared across the entire test suite.

Putting this at the project root means pytest discovers it regardless of
which subdirectory is being tested. This avoids the quirk where pytest
sometimes only loads ONE conftest.py when it finds a closer one to the
test file (which we hit when tests/e2e/conftest.py shadowed
tests/unit/conftest.py on some setups).

Layout:
  - This file: fixtures used by unit tests (DB, app, clients, users)
  - tests/e2e/conftest.py: fixtures specific to Playwright e2e tests
"""
import os
import sys
from pathlib import Path

import pytest

# IMPORTANT: env vars must be set BEFORE main / database / models are imported.
# But ONLY when running unit tests — for e2e runs we want the real .env.
#
# Detection: pytest passes the test paths via sys.argv. If any of them
# contains "e2e" we're in an e2e run and we shouldn't pollute env vars.
# Default behavior (pytest with no args) is unit tests, so we set the env.
import sys as _sys
_running_e2e = any("e2e" in arg for arg in _sys.argv)

if not _running_e2e:
    TEST_ENV = {
        "SESSION_SECRET": "test_secret_for_unit_tests_only",
        "ADMIN_USERNAME": "test_admin_seed",
        "ADMIN_PASSWORD": "seed_password_123",
        "RP_ID": "localhost",
        "RP_NAME": "CafeSync Test",
        "WEBAUTHN_ORIGINS": "http://localhost:8000",
        # Disable hardening features that are tested separately.
        # CSRF and rate limits are exercised in the Playwright e2e test;
        # they interfere with unit tests that POST many times rapidly or
        # without rendering a template that injects a token.
        "DISABLE_RATE_LIMIT": "1",
        "DISABLE_CSRF": "1",
    }
    for k, v in TEST_ENV.items():
        os.environ.setdefault(k, v)

# Make sure the project root is on sys.path so tests can `import main`, etc.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# --- Skip e2e fixtures from collection by unit-test runs ---
# When pytest collects from tests/unit/, the e2e fixtures (browser, page, etc.)
# come along for the ride because the e2e conftest is in a sibling dir. They
# don't interfere with unit tests, just listed when fixtures aren't found.


# ----------------------------------------------------------------------
# Unit-test fixtures
# ----------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """A fresh SQLite file per test."""
    path = tmp_path / "test_cafesync.db"
    monkeypatch.setenv("DB_PATH", str(path))
    return str(path)


@pytest.fixture
def app_module(db_path):
    """Re-imports main against a fresh DB. Returns the FastAPI app module.

    Each test gets its own engine bound to its own DB file, so we have to
    drop cached imports before re-importing.
    """
    for mod_name in list(sys.modules.keys()):
        if mod_name in (
            "main", "database", "models", "schemas", "auth_utils", "roles"
        ) or mod_name.startswith("routers"):
            del sys.modules[mod_name]

    import main  # noqa: F401 — triggers Base.metadata.create_all + admin seed
    return main


@pytest.fixture
def client(app_module):
    """TestClient that does NOT auto-follow redirects."""
    from fastapi.testclient import TestClient
    return TestClient(app_module.app, follow_redirects=False)


@pytest.fixture
def db(app_module):
    """A SQLAlchemy session for direct DB inspection in tests."""
    from database import SessionLocal
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# --- User factory + login helper ---

@pytest.fixture
def make_user(db):
    """Factory: creates a user with the given role, returns the User row.
    Stashes plaintext password as ._test_password for test convenience."""
    import models
    from auth_utils import hash_password
    from roles import Role

    def _make(username, role=Role.USER, password=None):
        password = password or f"pw_{username}_123"
        user = models.User(
            username=username,
            hashed_password=hash_password(password),
            role=role,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user._test_password = password
        return user

    return _make


@pytest.fixture
def login(client):
    """Helper: log a user in via the password flow."""
    def _login(user, password=None):
        password = password or getattr(user, "_test_password", None)
        if password is None:
            raise ValueError("login() needs a password — pass one or set _test_password on the user")
        response = client.post(
            "/login",
            data={"username": user.username, "password": password},
        )
        if response.status_code != 302:
            raise RuntimeError(
                f"Login as {user.username} failed: {response.status_code} {response.text[:200]}"
            )
        return client

    return _login


# --- Convenience fixtures for the four roles ---

@pytest.fixture
def admin_user(make_user):
    from roles import Role
    return make_user("admin_user", role=Role.ADMIN)


@pytest.fixture
def barista_user(make_user):
    from roles import Role
    return make_user("barista_user", role=Role.BARISTA)


@pytest.fixture
def regular_user(make_user):
    from roles import Role
    return make_user("regular_user", role=Role.USER)


@pytest.fixture
def viewer_user(make_user):
    from roles import Role
    return make_user("viewer_user", role=Role.VIEWER)


# --- Pre-authenticated clients per role ---
# Each role-client uses its OWN TestClient instance so they don't share
# session cookies. Without this, logging in as `regular_client` would
# clobber the `admin_client` session in tests that use both fixtures.

def _new_client_logged_in_as(app_module, user, password):
    from fastapi.testclient import TestClient
    c = TestClient(app_module.app, follow_redirects=False)
    response = c.post(
        "/login",
        data={"username": user.username, "password": password},
    )
    if response.status_code != 302:
        raise RuntimeError(
            f"Login as {user.username} failed: {response.status_code} {response.text[:200]}"
        )
    return c


@pytest.fixture
def admin_client(app_module, admin_user):
    return _new_client_logged_in_as(app_module, admin_user, admin_user._test_password)


@pytest.fixture
def barista_client(app_module, barista_user):
    return _new_client_logged_in_as(app_module, barista_user, barista_user._test_password)


@pytest.fixture
def regular_client(app_module, regular_user):
    return _new_client_logged_in_as(app_module, regular_user, regular_user._test_password)


@pytest.fixture
def viewer_client(app_module, viewer_user):
    return _new_client_logged_in_as(app_module, viewer_user, viewer_user._test_password)
