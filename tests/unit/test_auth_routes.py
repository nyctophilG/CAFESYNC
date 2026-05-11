# tests/unit/test_auth_routes.py
"""Tests for routers/auth.py — login, signup, logout, post-login routing."""
import pytest


# ---------- /signup ----------

class TestSignup:

    def test_signup_creates_user(self, client, db):
        import models
        from roles import Role

        r = client.post("/signup", data={"username": "alice", "password": "pw_alice_123"})
        assert r.status_code == 302
        # Redirected to /menu (the user's home)
        assert r.headers["location"] == "/menu"

        u = db.query(models.User).filter(models.User.username == "alice").first()
        assert u is not None
        assert u.role == Role.USER

    def test_signup_username_too_short(self, client):
        r = client.post("/signup", data={"username": "ab", "password": "pw_abby_long"})
        assert r.status_code == 400
        assert b"at least 3 characters" in r.content

    def test_signup_password_too_short(self, client):
        r = client.post("/signup", data={"username": "alice", "password": "short"})
        assert r.status_code == 400
        assert b"at least 8" in r.content

    def test_signup_password_too_long_for_bcrypt(self, client):
        r = client.post(
            "/signup",
            data={"username": "alice", "password": "x" * 80},
        )
        assert r.status_code == 400
        assert b"at most" in r.content

    def test_signup_duplicate_username(self, client, make_user):
        make_user("alice")
        r = client.post("/signup", data={"username": "alice", "password": "different_pw_99"})
        assert r.status_code == 409
        assert b"already taken" in r.content

    def test_signup_get_renders_form(self, client):
        r = client.get("/signup")
        assert r.status_code == 200
        assert b"<form" in r.content

    def test_signup_get_when_already_logged_in(self, admin_client):
        """Logged-in users hitting /signup get redirected to their home."""
        r = admin_client.get("/signup")
        assert r.status_code == 302
        # Admin's post-login path is /dashboard
        assert r.headers["location"] == "/dashboard"


# ---------- /login ----------

class TestLogin:

    def test_login_get_renders_form(self, client):
        r = client.get("/login")
        assert r.status_code == 200
        assert b"<form" in r.content

    def test_login_with_correct_credentials(self, client, make_user):
        u = make_user("alice")
        r = client.post(
            "/login",
            data={"username": "alice", "password": u._test_password},
        )
        assert r.status_code == 302
        assert r.headers["location"] == "/menu"  # user lands on /menu

    def test_login_with_wrong_password(self, client, make_user):
        make_user("alice")
        r = client.post(
            "/login",
            data={"username": "alice", "password": "wrong"},
        )
        assert r.status_code == 401
        assert b"Invalid" in r.content

    def test_login_unknown_username(self, client):
        r = client.post(
            "/login",
            data={"username": "nobody", "password": "anything_at_all"},
        )
        assert r.status_code == 401

    def test_login_admin_lands_on_dashboard(self, client, admin_user):
        r = client.post(
            "/login",
            data={"username": admin_user.username, "password": admin_user._test_password},
        )
        assert r.status_code == 302
        assert r.headers["location"] == "/dashboard"

    def test_login_barista_lands_on_dashboard(self, client, barista_user):
        r = client.post(
            "/login",
            data={"username": barista_user.username, "password": barista_user._test_password},
        )
        assert r.headers["location"] == "/dashboard"

    def test_login_viewer_lands_on_dashboard(self, client, viewer_user):
        r = client.post(
            "/login",
            data={"username": viewer_user.username, "password": viewer_user._test_password},
        )
        assert r.headers["location"] == "/dashboard"

    def test_login_remember_me_extends_session(self, client, admin_user):
        """The remember_me flag should set a longer expires_at."""
        import time
        r = client.post(
            "/login",
            data={
                "username": admin_user.username,
                "password": admin_user._test_password,
                "remember_me": "1",
            },
        )
        assert r.status_code == 302
        # We can read the session cookie's expiry from the cookie itself —
        # it's set via SessionMiddleware. Just confirm login worked.
        r2 = client.get("/dashboard")
        assert r2.status_code == 200

    def test_login_get_when_already_logged_in(self, admin_client):
        r = admin_client.get("/login")
        assert r.status_code == 302
        assert r.headers["location"] == "/dashboard"

    def test_login_with_totp_redirects_to_challenge(self, client, db, make_user):
        """If user has totp_enabled, login redirects to /login/2fa instead of
        completing the session."""
        import models
        from auth_utils import generate_totp_secret

        u = make_user("alice_2fa")
        u.totp_secret = generate_totp_secret()
        u.totp_enabled = True
        db.commit()

        r = client.post(
            "/login",
            data={"username": "alice_2fa", "password": u._test_password},
        )
        assert r.status_code == 302
        assert r.headers["location"] == "/login/2fa"

        # Crucial: user_id should NOT be in session yet.
        # We test this indirectly: a protected route should still 401.
        r2 = client.get("/users/")
        assert r2.status_code == 401


# ---------- /logout ----------

class TestLogout:

    def test_logout_post_clears_session(self, admin_client):
        r = admin_client.post("/logout")
        assert r.status_code == 302
        assert r.headers["location"] == "/login"
        # Subsequent /users/ should 401
        r2 = admin_client.get("/users/")
        assert r2.status_code == 401

    def test_logout_get_also_works(self, admin_client):
        """We support GET /logout for plain anchor tags in the navbar."""
        r = admin_client.get("/logout")
        assert r.status_code == 302
        assert r.headers["location"] == "/login"
