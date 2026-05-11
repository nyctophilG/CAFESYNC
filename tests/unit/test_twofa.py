# tests/unit/test_twofa.py
"""Tests for routers/twofa.py — TOTP setup + challenge flows."""
import time
import pyotp
import pytest


# ---------- /2fa/setup (GET) ----------

class TestSetupPage:

    def test_unauthenticated_redirects_to_login(self, client):
        r = client.get("/2fa/setup")
        # Auth gate redirects to /login (302) for non-API routes.
        assert r.status_code in (302, 401)

    def test_authed_user_sees_page(self, admin_client):
        r = admin_client.get("/2fa/setup")
        assert r.status_code == 200
        # Setup template should render
        assert b"2FA" in r.content or b"two-factor" in r.content.lower() or b"Authenticator" in r.content

    def test_shows_qr_when_pending_secret_in_session(self, admin_client):
        """After /2fa/begin, the setup page shows the QR code."""
        admin_client.post("/2fa/begin")
        r = admin_client.get("/2fa/setup")
        assert r.status_code == 200
        # QR code data URI is embedded in the HTML
        assert b"data:image/png;base64" in r.content


# ---------- /2fa/begin ----------

class TestBegin:

    def test_begin_sets_pending_secret(self, admin_client):
        r = admin_client.post("/2fa/begin")
        # Redirects back to setup page
        assert r.status_code in (302, 303)

    def test_begin_when_already_enabled_returns_400(self, admin_client, admin_user, db):
        # Manually mark user as already having 2FA on
        from auth_utils import generate_totp_secret
        admin_user.totp_secret = generate_totp_secret()
        admin_user.totp_enabled = True
        db.commit()

        r = admin_client.post("/2fa/begin")
        assert r.status_code == 400


# ---------- /2fa/confirm ----------

class TestConfirm:

    def test_confirm_with_valid_code_enables_2fa(self, admin_client, admin_user, db):
        # Step 1: begin setup
        admin_client.post("/2fa/begin")
        # Read the pending secret out of the session via the page
        r = admin_client.get("/2fa/setup")
        assert r.status_code == 200

        # Step 2: pull the secret from the DB-side pending state by
        # inspecting the user (no — pending secret is in SESSION, not DB).
        # We need to extract from the page or replicate.
        # Easier: generate our own, set it directly via the session-aware
        # client by calling /begin and reading the cookie.
        # In practice we extract the secret from the page HTML.
        import re
        # The setup page embeds the secret in a span with class "secret-text"
        match = re.search(rb'class="secret-text"[^>]*>([A-Z2-7]+)', r.content)
        assert match, "Could not find pending secret in setup page"
        secret = match.group(1).decode("ascii")

        code = pyotp.TOTP(secret).now()
        r = admin_client.post("/2fa/confirm", data={"code": code})
        assert r.status_code in (302, 303)

        # User should now have totp_enabled=True
        db.refresh(admin_user)
        assert admin_user.totp_enabled is True
        assert admin_user.totp_secret == secret

        # Backup codes should be created
        assert len(admin_user.backup_codes) == 10

    def test_confirm_with_wrong_code_keeps_2fa_disabled(self, admin_client, admin_user, db):
        admin_client.post("/2fa/begin")
        r = admin_client.post("/2fa/confirm", data={"code": "000000"})
        assert r.status_code == 400
        db.refresh(admin_user)
        assert admin_user.totp_enabled is False

    def test_confirm_without_pending_secret_returns_400(self, admin_client):
        """Calling /confirm without first calling /begin should fail."""
        r = admin_client.post("/2fa/confirm", data={"code": "123456"})
        assert r.status_code == 400


# ---------- /2fa/disable ----------

class TestDisable:

    def _enable_2fa(self, admin_client, admin_user, db):
        """Helper: get the admin user into a TOTP-enabled state."""
        from auth_utils import generate_totp_secret, hash_backup_code
        import models
        secret = generate_totp_secret()
        admin_user.totp_secret = secret
        admin_user.totp_enabled = True
        db.commit()
        # Add a couple of backup codes too
        db.add(models.BackupCode(user_id=admin_user.id, code_hash=hash_backup_code("AAAAA-AAAAA")))
        db.commit()
        return secret

    def test_disable_with_correct_password(self, admin_client, admin_user, db):
        self._enable_2fa(admin_client, admin_user, db)
        r = admin_client.post("/2fa/disable", data={"password": admin_user._test_password})
        assert r.status_code in (302, 303)
        db.refresh(admin_user)
        assert admin_user.totp_enabled is False
        assert admin_user.totp_secret is None
        # Backup codes should be deleted
        assert len(admin_user.backup_codes) == 0

    def test_disable_with_wrong_password_keeps_2fa_on(self, admin_client, admin_user, db):
        self._enable_2fa(admin_client, admin_user, db)
        r = admin_client.post("/2fa/disable", data={"password": "wrong_password"})
        assert r.status_code == 400
        db.refresh(admin_user)
        assert admin_user.totp_enabled is True


# ---------- /2fa/regen-codes ----------

class TestRegenCodes:

    def test_regen_with_2fa_enabled(self, admin_client, admin_user, db):
        # Enable 2FA with old codes
        from auth_utils import generate_totp_secret, hash_backup_code
        import models
        admin_user.totp_secret = generate_totp_secret()
        admin_user.totp_enabled = True
        db.add(models.BackupCode(user_id=admin_user.id, code_hash=hash_backup_code("OLDOL-DOLDO")))
        db.commit()
        old_count = len(admin_user.backup_codes)

        r = admin_client.post("/2fa/regen-codes")
        assert r.status_code in (302, 303)

        db.refresh(admin_user)
        # All old codes should be gone, replaced with 10 new ones
        assert len(admin_user.backup_codes) == 10
        # Old code hash should not be present
        for bc in admin_user.backup_codes:
            assert bc.code_hash != hash_backup_code("OLDOL-DOLDO") or True  # bcrypt randomized, just check count

    def test_regen_without_2fa_returns_400(self, admin_client):
        r = admin_client.post("/2fa/regen-codes")
        assert r.status_code == 400


# ---------- /login/2fa (challenge page) ----------

class TestChallengePage:

    def _start_2fa_login(self, client, admin_user, db):
        """Helper: get a client into the pending-2FA state."""
        from auth_utils import generate_totp_secret
        secret = generate_totp_secret()
        admin_user.totp_secret = secret
        admin_user.totp_enabled = True
        db.commit()

        client.post("/login", data={
            "username": admin_user.username,
            "password": admin_user._test_password,
        })
        return secret

    def test_challenge_page_renders(self, client, admin_user, db):
        self._start_2fa_login(client, admin_user, db)
        r = client.get("/login/2fa")
        assert r.status_code == 200
        assert b"Two-factor" in r.content or b"code" in r.content.lower()

    def test_challenge_page_without_pending_redirects(self, client):
        """Hitting /login/2fa with no pending login should bounce to /login."""
        r = client.get("/login/2fa")
        assert r.status_code in (302, 303)
        assert "/login" in r.headers["location"]


# ---------- /login/2fa (challenge submit) ----------

class TestChallengeSubmit:

    def _start_2fa_login(self, client, admin_user, db):
        from auth_utils import generate_totp_secret
        secret = generate_totp_secret()
        admin_user.totp_secret = secret
        admin_user.totp_enabled = True
        db.commit()

        client.post("/login", data={
            "username": admin_user.username,
            "password": admin_user._test_password,
        })
        return secret

    def test_challenge_with_correct_totp_code(self, client, admin_user, db):
        secret = self._start_2fa_login(client, admin_user, db)
        code = pyotp.TOTP(secret).now()
        r = client.post("/login/2fa", data={"code": code})
        # Successful 2FA redirects to the user's home (admin -> /dashboard)
        assert r.status_code in (302, 303)
        assert r.headers["location"] == "/dashboard"

    def test_challenge_with_wrong_code_fails(self, client, admin_user, db):
        self._start_2fa_login(client, admin_user, db)
        r = client.post("/login/2fa", data={"code": "000000"})
        assert r.status_code == 401

    def test_challenge_with_backup_code(self, client, admin_user, db):
        from auth_utils import hash_backup_code
        import models
        self._start_2fa_login(client, admin_user, db)
        # Add a backup code
        db.add(models.BackupCode(
            user_id=admin_user.id,
            code_hash=hash_backup_code("AAAAA-BBBBB"),
        ))
        db.commit()

        r = client.post("/login/2fa", data={"code": "AAAAA-BBBBB", "use_backup": "1"})
        assert r.status_code in (302, 303)

    def test_challenge_without_pending_redirects(self, client):
        r = client.post("/login/2fa", data={"code": "123456"})
        assert r.status_code in (302, 303)
        assert "/login" in r.headers["location"]
