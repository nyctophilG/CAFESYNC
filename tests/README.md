# CafeSync Test Suite

Two layers:

- **Unit tests** (`tests/unit/`) — fast, isolated, target ~90% coverage. Each test gets a fresh SQLite file. No browser, no live server.
- **End-to-end tests** (`tests/e2e/`) — Playwright drives a real browser against a running server. One sequential story covering every feature.

## One-time setup

```bash
# from your virtualenv
pip install -r requirements-dev.txt

# Playwright needs to download a browser binary the first time
playwright install chromium
```

## Running unit tests

```bash
# all unit tests
pytest

# with coverage report
pytest --cov

# verbose
pytest -v

# a single file / class / test
pytest tests/unit/test_orders.py
pytest tests/unit/test_orders.py::TestListOrders
pytest tests/unit/test_orders.py::TestListOrders::test_admin_can_list
```

The first run takes ~30s because bcrypt is deliberately slow. Subsequent runs the same.

## Running end-to-end tests

E2E tests need a running server. Two terminals:

**Terminal 1** — fresh server:
```bash
rm -f cafesync.db
uvicorn main:app
```

**Terminal 2** — the tests:
```bash
# headless (default, fast)
pytest tests/e2e/

# watch the browser do the work
pytest tests/e2e/ --headed

# slow it down so you can see what's happening
pytest tests/e2e/ --headed --slowmo=500
```

The single `test_full_journey` walks through every feature in order, like a story. If a step fails, pytest tells you exactly which feature broke.

### What the journey covers

1. Signup as a regular user → land on `/menu`
2. Place an order from the menu
3. User can't reach `/dashboard` (gets redirected to `/menu`)
4. Admin login → full dashboard with User Management, telemetry, traffic generator
5. Admin sees the user's order in the queue
6. Admin clicks "Serve" → order completes
7. Admin promotes user to **barista**
8. Self-protection: admin can't change their own role
9. Barista login → Barista Station UI (no telemetry, no user mgmt)
10. Barista can serve another user's order
11. Admin promotes user to **viewer**
12. Viewer login → dashboard with controls hidden
13. Viewer on `/menu` can browse but not order
14. Admin enables TOTP on their account
15. Backup codes captured at setup
16. Login with TOTP code
17. Login with backup code
18. Backup code single-use enforcement (reuse fails, fresh code works)
19. Passkey UI element exists on login page

Passkey *registration* and *login* require a real authenticator (Touch ID, security key, etc.) so they are demonstrated manually rather than in Playwright.

## Coverage threshold

`.coveragerc` sets `fail_under = 90`. If coverage drops below 90%, `pytest --cov` exits with a non-zero status code (useful for CI).

To see exactly which lines aren't covered:
```bash
pytest --cov --cov-report=term-missing
```

## CI

`.github/workflows/tests.yml` runs both layers on every push. Unit tests always run; E2E tests start uvicorn in the background and run against it.
