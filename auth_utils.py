# auth_utils.py
"""Authentication and authorization utilities.

Password hashing uses bcrypt directly (not via passlib, which is no longer
maintained and broke with bcrypt 5.x). Sessions are stored in signed cookies
via Starlette's SessionMiddleware, so we only keep small identifiers
(user id, username, role) in the cookie payload — never the password or hash.

This module exposes three FastAPI dependencies for endpoint protection:
  - get_current_user: any authenticated user
  - require_staff:    admin or barista (anyone with dashboard access)
  - require_admin:    admin only

Use 401 vs 403 deliberately:
  - 401 Unauthorized: not logged in (or session expired)
  - 403 Forbidden:    logged in, but lacks the required role
"""
import bcrypt
from fastapi import Request, HTTPException, status, Depends
from sqlalchemy.orm import Session

import models
from database import get_db, SessionLocal
from roles import Role, STAFF_ROLES

# bcrypt's algorithmic limit: it only hashes the first 72 bytes of input.
# Rather than silently truncating (a footgun), we reject anything longer at
# the application layer with a clear error.
BCRYPT_MAX_BYTES = 72

# Pre-computed dummy hash for constant-time auth: when a username doesn't
# exist, we still run a hash check so response timing matches the
# wrong-password path. Without this, attackers can enumerate valid
# usernames by measuring response times.
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
    if len(encoded) > BCRYPT_MAX_BYTES:
        return False
    try:
        return bcrypt.checkpw(encoded, hashed.encode("utf-8"))
    except ValueError:
        # Malformed hash in the DB — treat as a failed verification rather
        # than letting it crash the login endpoint.
        return False


def authenticate_user(db: Session, username: str, password: str):
    """Returns the User if credentials are valid, otherwise None.

    Returns the same None for both 'user not found' and 'wrong password',
    and runs a dummy hash check on the not-found path so response timing
    can't be used to enumerate valid usernames.
    """
    user = db.query(models.User).filter(
        models.User.username == username
    ).first()
    if not user:
        # Burn roughly the same time as a real verification.
        bcrypt.checkpw(b"dummy", _DUMMY_HASH)
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


# --- Dependencies ---

def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Returns the current authenticated User, or raises 401.

    Use directly when an endpoint accepts any authenticated user regardless
    of role (e.g. POST /orders/ where customers can place orders).
    """
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    user = db.query(models.User).filter(
        models.User.id == user_id
    ).first()
    if not user:
        # Session references a deleted user — treat as unauthenticated.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalid",
        )
    return user


def require_staff(current_user: models.User = Depends(get_current_user)):
    """Allows admin or barista. Customers get 403."""
    if current_user.role not in STAFF_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff role required",
        )
    return current_user


def require_admin(current_user: models.User = Depends(get_current_user)):
    """Admin only. Baristas and customers get 403."""
    if current_user.role != Role.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return current_user


# --- Bootstrap ---

def seed_initial_admin(username: str, password: str) -> None:
    """Creates the bootstrap admin from env vars if no admin exists yet.

    Idempotent: if any user with role=admin exists, this is a no-op. That
    means rotating ADMIN_PASSWORD in .env won't update the existing admin —
    intentional, since otherwise anyone with .env write access could
    silently take over an existing account. Use the user management UI
    (or delete the row manually) to rotate credentials.
    """
    db = SessionLocal()
    try:
        existing_admin = db.query(models.User).filter(
            models.User.role == Role.ADMIN
        ).first()
        if existing_admin:
            return
        admin = models.User(
            username=username,
            hashed_password=hash_password(password),
            role=Role.ADMIN,
        )
        db.add(admin)
        db.commit()
    finally:
        db.close()
