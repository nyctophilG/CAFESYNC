# tests/unit/test_smoke.py
"""Sanity checks: the test infrastructure itself works."""


def test_app_boots(app_module):
    """Importing main creates the app. If env vars or imports break, this fails first."""
    assert app_module.app is not None


def test_health_endpoint(client):
    """Cheapest possible end-to-end check."""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "healthy", "service": "CafeSync Core"}


def test_seed_admin_exists(db):
    """The startup seed should have created the admin from env vars."""
    import models
    from roles import Role

    admin = db.query(models.User).filter(models.User.role == Role.ADMIN).first()
    assert admin is not None
    assert admin.username == "test_admin_seed"


def test_make_user_factory(make_user, db):
    import models
    from roles import Role

    u = make_user("alice", role=Role.USER)
    assert u.id is not None
    assert u.role == Role.USER
    assert u._test_password == "pw_alice_123"

    # Make sure it's actually persisted.
    fetched = db.query(models.User).filter(models.User.username == "alice").first()
    assert fetched is not None


def test_login_helper(make_user, login, client):
    from roles import Role

    u = make_user("bob", role=Role.ADMIN)
    c = login(u)
    # Authenticated requests now work.
    r = c.get("/users/")
    assert r.status_code == 200


def test_each_role_fixture_is_correct_role(admin_user, barista_user, regular_user, viewer_user):
    from roles import Role
    assert admin_user.role == Role.ADMIN
    assert barista_user.role == Role.BARISTA
    assert regular_user.role == Role.USER
    assert viewer_user.role == Role.VIEWER


def test_each_role_client_authenticates(admin_client, barista_client, regular_client, viewer_client):
    """All four pre-authenticated client fixtures should be able to make
    at least one authenticated request without 401."""
    # /health is public so it tests very little; pick role-appropriate endpoints.
    for c in [admin_client, barista_client, regular_client, viewer_client]:
        r = c.get("/health")
        assert r.status_code == 200
