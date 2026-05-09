# auth_utils.py
"""Authentication utilities: password hashing, session helpers, and the
auth dependency used to protect routes.

We use the `bcrypt` library directly (not via passlib, which is no longer
maintained and broke with bcrypt 5.x). Sessions are stored in signed cookies
via Starlette's SessionMiddleware, so we only keep small identifiers
(user id, username) in the cookie payload — never the password or its hash.
"""
import bcrypt
from fastapi import Request, HTTPException, status, Depends
from sqlalchemy.orm import Session

import models
from database import get_db, SessionLocal

# bcrypt's algorithmic limit: it only hashes the first 72 bytes of input.
# Rather than silently truncating (which is a footgun), we reject anything
# longer at the application layer with a clear error.
BCRYPT_MAX_BYTES = 72

# A pre-computed bcrypt hash of an arbitrary string. We run verify_password()
# against this whenever the supplied username doesn't exist, so the response
# time of "user not found" matches "wrong password" — preventing username
# enumeration via timing attacks.
_DUMMY_HASH = bcrypt.hashpw(b"dummy_password_for_timing", bcrypt.gensalt(rounds=12))


def hash_password(plain: str) -> str:
    """Hashes a plaintext password with bcrypt (cost factor 12).

    Raises ValueError if the password exceeds bcrypt's 72-byte limit, so
    we never silently truncate user input.
    """
    encoded = plain.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_BYTES:
        raise ValueError(
            f"Password must be at most {BCRYPT_MAX_BYTES} bytes when "
            f"UTF-8 encoded (got {len(encoded)} bytes)."
        )
    hashed = bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=12))
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time check of a plaintext password against a stored hash."""
    encoded = plain.encode("utf-8")
    # Reject over-limit passwords up front rather than letting bcrypt raise.
    if len(encoded) > BCRYPT_MAX_BYTES:
        return False
    try:
        return bcrypt.checkpw(encoded, hashed.encode("utf-8"))
    except ValueError:
        # Malformed hash in the DB — treat as a failed verification rather
        # than letting it crash the login endpoint.
        return False


def authenticate_admin(db: Session, username: str, password: str):
    """Returns the AdminUser if credentials are valid, otherwise None.

    We deliberately return the same None for both 'user not found' and
    'wrong password', and run a dummy hash check on the not-found path so
    response timing can't be used to enumerate valid usernames.
    """
    user = db.query(models.AdminUser).filter(
        models.AdminUser.username == username
    ).first()
    if not user:
        # Burn roughly the same time as a real verification.
        bcrypt.checkpw(b"dummy", _DUMMY_HASH)
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def get_current_admin(request: Request, db: Session = Depends(get_db)):
    """FastAPI dependency: returns the current AdminUser or raises 401.

    Use this on JSON API routes (e.g. /orders, /telemetry) where a redirect
    wouldn't make sense. For HTML routes we rely on the auth-gate middleware
    in main.py instead, which redirects to /login.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    user = db.query(models.AdminUser).filter(
        models.AdminUser.id == user_id
    ).first()
    if not user:
        # Session references a deleted user — treat as unauthenticated.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalid",
        )
    return user


def seed_initial_admin(username: str, password: str) -> None:
    """Creates the bootstrap admin from env vars if no admin exists yet.

    Idempotent: if any AdminUser row exists, this is a no-op. That means
    rotating the .env password won't update the existing admin — that's
    intentional, since otherwise anyone with .env write access could
    silently take over an existing account. Use a proper password-reset
    flow (or delete the row manually) to rotate credentials.
    """
    db = SessionLocal()
    try:
        existing = db.query(models.AdminUser).first()
        if existing:
            return
        admin = models.AdminUser(
            username=username,
            hashed_password=hash_password(password),
        )
        db.add(admin)
        db.commit()
    finally:
        db.close()
