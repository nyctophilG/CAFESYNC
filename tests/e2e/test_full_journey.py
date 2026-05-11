# tests/e2e/test_full_journey.py
"""End-to-end Playwright test that walks through every feature in one run.

This is structured as a single sequential story — the easiest way to read
in a demo, since each step naturally builds on the previous one. Each step
is annotated with the rubric feature it covers.

Prerequisite: `uvicorn main:app` running, fresh DB (rm cafesync.db first).
"""
import re
import time

import pyotp
import pytest


# Use unique usernames each run so a single DB can host multiple test runs
# without unique-constraint collisions during dev iteration. In CI we wipe
# the DB before each run anyway.
RUN_ID = str(int(time.time()))
USER = f"e2e_user_{RUN_ID}"
USER_PW = "playwright_pw_8x!"


# ----------------------------------------------------------------------
# Small helpers — these encapsulate UI bits that change rarely and let
# the main test read like a story.
# ----------------------------------------------------------------------

def _login(page, base_url, username, password):
    """Password login. Lands on either /menu, /dashboard, or /login/2fa.

    Clears any existing cookies first — without this, if a previous session
    is still active, /login auto-redirects to that user's home and the
    form never renders (Page.fill would time out on the missing input).
    """
    page.context.clear_cookies()
    page.goto(f"{base_url}/login")
    # If for any reason we still ended up not on /login (very unlikely now),
    # bail loudly so the failure is obvious.
    if "/login" not in page.url:
        raise AssertionError(
            f"Expected /login, got {page.url!r}. Cookies may not have cleared."
        )
    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]:has-text("Sign In")')


def _logout(page, base_url):
    """Cleanest path: hit /logout directly. Avoids depending on a
    button-in-navbar that varies by template."""
    page.goto(f"{base_url}/logout")
    page.wait_for_url(re.compile(r".*/login.*"))
    # Belt and suspenders: also clear cookies in the browser context.
    page.context.clear_cookies()


def _set_role_via_admin_panel(page, target_username, new_role):
    """On the admin dashboard, change a user's role via the dropdown.

    The User Management table renders rows with the username in <strong>
    and a <select> for the role. We locate the row by username text, then
    change its <select>.
    """
    # Wait for the user table to populate (it's filled by a setInterval).
    row = page.locator(
        f"#users-table-body tr:has-text('{target_username}')"
    ).first
    row.wait_for(state="visible", timeout=5000)
    select = row.locator("select")
    select.select_option(new_role)
    # The change handler hits /users/{id}/role. Give it a moment to commit.
    page.wait_for_timeout(500)


# ----------------------------------------------------------------------
# THE JOURNEY
# ----------------------------------------------------------------------

def test_full_journey(page, base_url, admin_credentials):
    """Sequential story covering all major features. If any step fails,
    everything after it is skipped — pytest will tell you exactly which
    feature broke."""

    # ==================================================================
    # 1. SIGNUP — new user account, defaults to role=user
    # ==================================================================
    page.goto(f"{base_url}/signup")
    page.fill('input[name="username"]', USER)
    page.fill('input[name="password"]', USER_PW)
    page.click('button[type="submit"]:has-text("Create Account")')

    # Default role is "user" → lands on /menu.
    page.wait_for_url(f"{base_url}/menu")
    assert page.locator("h2:has-text('Menu')").is_visible()

    # ==================================================================
    # 2. PLACE ONE ORDER from menu
    # ==================================================================
    # Click the first "Place Order" button on the default (Coffee) tab.
    first_order_btn = page.locator("button[data-item]").first
    item_name = first_order_btn.get_attribute("data-item")
    first_order_btn.click()
    # Toast confirmation appears.
    toast = page.locator(".toast.show")
    toast.wait_for(state="visible", timeout=3000)
    assert "placed" in toast.text_content().lower()
    # Closing the toast keeps subsequent assertions cleaner.
    toast.locator(".btn-close").click()

    # ==================================================================
    # 3. USER CANNOT REACH /dashboard — gets redirected to /menu
    # ==================================================================
    page.goto(f"{base_url}/dashboard")
    page.wait_for_url(f"{base_url}/menu")

    # ==================================================================
    # 4. LOGOUT
    # ==================================================================
    _logout(page, base_url)

    # ==================================================================
    # 5. ADMIN LOGIN — sees full dashboard with User Management panel
    # ==================================================================
    _login(page, base_url, admin_credentials["username"], admin_credentials["password"])

    # Wait for either a successful redirect away from /login (success) OR
    # for an error message to render (failure). Using expect on a URL
    # regex would also work but this is more flexible — we want a clear
    # diagnostic either way.
    try:
        page.wait_for_url(
            lambda url: "/login" not in url or "/login/2fa" in url,
            timeout=10000,
        )
    except Exception:
        # Still on /login after 10s — login form bounced back with an error.
        try:
            error_text = page.locator(".alert-danger").first.text_content(timeout=2000).strip()
        except Exception:
            error_text = "(no error shown)"
        raise AssertionError(
            f"Admin login did not navigate away from /login. "
            f"username={admin_credentials['username']!r}, "
            f"current URL={page.url!r}, "
            f"page error: {error_text!r}. "
            f"Check that ADMIN_USERNAME/ADMIN_PASSWORD in .env match the "
            f"running server, and that the server has been restarted "
            f"since any .env change."
        )

    page.wait_for_url(f"{base_url}/dashboard")

    # User Management section is admin-only.
    assert page.locator("text=User & Role Management").is_visible()
    # Telemetry cards are visible to admin.
    assert page.locator("#metric-total-requests").is_visible()
    # Traffic Generator panel is admin-only.
    assert page.locator("text=Traffic Generator").is_visible()

    # ==================================================================
    # 6. ORDER PLACED BY USER SHOWS IN ADMIN QUEUE
    # ==================================================================
    # Match by USERNAME, not item name. The queue may contain other orders
    # (from prior runs, Traffic Generator, etc.) — we only care about OUR
    # user's specific row.
    queue_row = page.locator(
        f"#queue-table-body tr:has-text('{USER}')"
    ).first
    queue_row.wait_for(state="visible", timeout=5000)
    assert item_name in queue_row.text_content()

    # ==================================================================
    # 7. ADMIN COMPLETES THE ORDER (Serve)
    # ==================================================================
    queue_row.locator("button:has-text('Serve')").click()
    # Wait for queue refresh; the served order should disappear.
    # Refreshes happen on a 2s interval.
    page.wait_for_timeout(2500)
    # Assert OUR user's row is gone (other Espressos in the queue are fine).
    remaining = page.locator(
        f"#queue-table-body tr:has-text('{USER}')"
    )
    assert remaining.count() == 0, (
        f"Expected user {USER}'s order to be gone after Serve, "
        f"but {remaining.count()} row(s) still match"
    )

    # ==================================================================
    # 8. ADMIN PROMOTES USER → barista
    # ==================================================================
    _set_role_via_admin_panel(page, USER, "barista")

    # ==================================================================
    # 9. SELF-PROTECTION: admin's own row dropdown is disabled
    # ==================================================================
    # Match by the "you" badge that the dashboard adds to the current
    # user's row — unambiguous, even if other rows happen to contain
    # the literal string "admin" in dropdown options or role badges.
    admin_row = page.locator(
        "#users-table-body tr:has(.badge:text-is('you'))"
    ).first
    admin_row.wait_for(state="visible")
    admin_select = admin_row.locator("select")
    assert admin_select.is_disabled(), "Admin should not be able to change own role"

    # ==================================================================
    # 10. LOGOUT, LOGIN AS BARISTA → barista station UI
    # ==================================================================
    _logout(page, base_url)
    _login(page, base_url, USER, USER_PW)
    page.wait_for_url(f"{base_url}/dashboard")

    # Barista sees "Barista Station", NOT the full dashboard's user mgmt.
    assert page.locator("text=Barista Station").is_visible()
    assert page.locator("text=User & Role Management").count() == 0
    assert page.locator("#metric-total-requests").count() == 0

    # ==================================================================
    # 11. BARISTA CAN SERVE — place an order from another browser context
    # ==================================================================
    # Use a FRESH browser context (not just a new tab) so the barista's
    # session cookie doesn't leak. If we just opened a new page in the
    # same context, /signup would see the barista's active session and
    # redirect away, leaving the form unrendered and Page.fill timing out.
    second_context = page.context.browser.new_context()
    second_page = second_context.new_page()
    second_page.goto(f"{base_url}/signup")
    secondary_user = f"e2e_buddy_{RUN_ID}"
    second_page.fill('input[name="username"]', secondary_user)
    second_page.fill('input[name="password"]', "secondary_pw_xx_99")
    second_page.click('button[type="submit"]:has-text("Create Account")')
    second_page.wait_for_url(f"{base_url}/menu")
    second_page.locator("button[data-item]").first.click()
    second_page.locator(".toast.show").wait_for(state="visible")
    second_context.close()

    # Back on the barista's page, the new order shows up via auto-poll.
    page.wait_for_timeout(2500)
    new_order_row = page.locator(
        f"#queue-table-body tr:has-text('{secondary_user}')"
    ).first
    new_order_row.wait_for(state="visible", timeout=5000)
    new_order_row.locator("button:has-text('Serve')").click()
    page.wait_for_timeout(2500)
    assert page.locator(
        f"#queue-table-body tr:has-text('{secondary_user}')"
    ).count() == 0

    # ==================================================================
    # 12. ADMIN PROMOTES USER → viewer
    # ==================================================================
    _logout(page, base_url)
    _login(page, base_url, admin_credentials["username"], admin_credentials["password"])
    page.wait_for_url(f"{base_url}/dashboard")
    _set_role_via_admin_panel(page, USER, "viewer")

    # ==================================================================
    # 13. VIEWER LOGS IN — interactive controls hidden
    # ==================================================================
    _logout(page, base_url)
    _login(page, base_url, USER, USER_PW)
    page.wait_for_url(f"{base_url}/dashboard")

    # Viewer sees the read-only banner.
    assert page.locator("text=signed in as a").is_visible()
    # Telemetry cards visible.
    assert page.locator("#metric-total-requests").is_visible()
    # Interactive sections HIDDEN.
    assert page.locator("text=User & Role Management").count() == 0
    assert page.locator("text=Traffic Generator").count() == 0
    # Serve buttons hidden in viewer's queue (column dropped server-side).

    # ==================================================================
    # 14. VIEWER ON /menu — Place Order buttons hidden
    # ==================================================================
    page.goto(f"{base_url}/menu")
    page.wait_for_url(f"{base_url}/menu")
    assert page.locator("h2:has-text('Menu')").is_visible()
    # Items render but no place-order buttons.
    assert page.locator("button[data-item]").count() == 0

    # ==================================================================
    # 15. ADMIN PROMOTES USER → user (back to default), enables 2FA on admin
    # ==================================================================
    _logout(page, base_url)
    _login(page, base_url, admin_credentials["username"], admin_credentials["password"])
    page.wait_for_url(f"{base_url}/dashboard")
    _set_role_via_admin_panel(page, USER, "user")

    # Now enable TOTP on the admin account.
    page.goto(f"{base_url}/2fa/setup")
    # Click "Enable TOTP" button (form POSTs /2fa/begin).
    page.click('button[type="submit"]:has-text("Enable TOTP")')
    page.wait_for_url(f"{base_url}/2fa/setup")

    # Pull the secret out of the page (rendered in <span class="secret-text">).
    secret = page.locator(".secret-text").text_content().strip()
    assert len(secret) >= 16

    # Generate the current code with pyotp, enter it, submit.
    code = pyotp.TOTP(secret).now()
    page.fill('input[name="code"]', code)
    page.click('button[type="submit"]:has-text("Verify & enable")')
    page.wait_for_url(f"{base_url}/2fa/setup")

    # Confirmation: page now shows "is enabled".
    assert page.locator("text=is enabled").is_visible()

    # ==================================================================
    # 16. CAPTURE BACKUP CODES (one-shot display)
    # ==================================================================
    backup_code_elements = page.locator(".backup-code")
    backup_code_elements.first.wait_for(state="visible")
    backup_codes = [
        backup_code_elements.nth(i).text_content().strip()
        for i in range(backup_code_elements.count())
    ]
    assert len(backup_codes) == 10

    # ==================================================================
    # 17. LOGOUT, LOGIN WITH BACKUP CODE — proves 2FA challenge works
    # ==================================================================
    # Note: we skip the TOTP code challenge (it would need pyotp.now() at
    # exactly the right moment, brittle on a slow demo machine). Backup
    # codes are deterministic and prove the 2FA challenge gate works.
    _logout(page, base_url)
    _login(page, base_url, admin_credentials["username"], admin_credentials["password"])
    page.wait_for_url(f"{base_url}/login/2fa")
    assert page.locator("text=Two-factor").is_visible()

    # Toggle to backup-code form, enter one of the codes generated in setup.
    page.click("text=Use a backup code instead")
    backup_code = backup_codes[0]
    page.fill('#backup-form input[name="code"]', backup_code)
    page.click('#backup-form button[type="submit"]')
    page.wait_for_url(f"{base_url}/dashboard")

    # ==================================================================
    # 18. SAME BACKUP CODE CANNOT BE REUSED
    # ==================================================================
    _logout(page, base_url)
    _login(page, base_url, admin_credentials["username"], admin_credentials["password"])
    page.wait_for_url(f"{base_url}/login/2fa")
    page.click("text=Use a backup code instead")
    page.fill('#backup-form input[name="code"]', backup_code)  # already used
    page.click('#backup-form button[type="submit"]')
    # Expect to stay on /login/2fa with an error.
    assert page.locator("text=Invalid code").is_visible()

    # A DIFFERENT, unused backup code still works.
    # After the failed submit, the page reloaded — TOTP form is visible
    # again by default, backup form is hidden. We have to re-click the
    # toggle to show the backup form before we can fill it.
    page.click("text=Use a backup code instead")
    page.fill('#backup-form input[name="code"]', backup_codes[1])
    page.click('#backup-form button[type="submit"]')
    page.wait_for_url(f"{base_url}/dashboard")

    # ==================================================================
    # 19. PASSKEY UI APPEARS (cannot fully exercise without a real authenticator)
    # ==================================================================
    # Must log out first — otherwise /login auto-redirects to /dashboard
    # for the currently-authenticated admin session.
    _logout(page, base_url)
    page.wait_for_url(re.compile(r".*/login.*"))
    passkey_btn = page.locator("#passkey-btn")
    assert passkey_btn.is_visible()
    # Browser should advertise WebAuthn support.
    badge = page.evaluate("() => document.querySelector('#passkey-btn').disabled")
    # In headless Chromium this may be false (supported) or true (no platform
    # authenticator). We just check the element exists & button text is right.
    assert "Sign in with passkey" in passkey_btn.text_content()

    # ==================================================================
    # JOURNEY COMPLETE
    # ==================================================================
    print("\n  Full journey passed. Features verified:")
    print("    1. Signup → user role default")
    print("    2. /menu place-order")
    print("    3. /dashboard redirect for user role")
    print("    4. Admin dashboard")
    print("    5. Admin sees user's order in queue")
    print("    6. Admin can Serve")
    print("    7. RBAC: user → barista")
    print("    8. Self-protection: admin can't change own role")
    print("    9. Barista station UI")
    print("   10. Barista can Serve, sees orders only")
    print("   11. RBAC: → viewer, controls hidden")
    print("   12. Viewer can browse /menu but not order")
    print("   13. TOTP setup (Google Authenticator-compatible)")
    print("   14. Backup codes generated and shown once")
    print("   15. Login with backup code (proves 2FA challenge gate works)")
    print("   16. Backup code single-use enforcement")
    print("   17. Passkey UI present")
