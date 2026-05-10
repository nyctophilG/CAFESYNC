# auth_utils.py
"""Authentication and authorization utilities.

Password hashing uses bcrypt. TOTP via pyotp. WebAuthn handled in
routers/passkeys.py.

Dependencies for endpoint protection:
  get_current_user      — any authenticated user
  require_admin         — admin only
  require_fulfillment   — admin or barista (can mark orders complete)
  require_dashboard     — admin or viewer (can see the ops dashboard)
"""
import base64
import io
import secrets
from typing import List

import bcrypt
import pyotp
import qrcode
from fastapi import Request, HTTPException, status, Depends
from sqlalchemy.orm import Session

import models
from database import get_db, SessionLocal
from roles import Role, ORDER_FULFILLMENT_ROLES, DASHBOARD_ROLES

BCRYPT_MAX_BYTES = 72
_DUMMY_HASH = bcrypt.hashpw(b"dummy_password_for_timing", bcrypt.gensalt(rounds=12))

TOTP_ISSUER = "CafeSync"
TOTP_VALID_WINDOW = 1
BACKUP_CODE_COUNT = 10
BACKUP_CODE_LENGTH = 10


# --- Password hashing ---

def hash_password(plain: str) -> str:
    encoded = plain.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_BYTES:
        raise ValueError(
            f"Password must be at most {BCRYPT_MAX_BYTES} bytes when "
            f"UTF-8 encoded (got {len(encoded)} bytes)."
        )
    hashed = bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=12))
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    encoded = plain.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_BYTES:
        return False
    try:
        return bcrypt.checkpw(encoded, hashed.encode("utf-8"))
    except ValueError:
        return False


def authenticate_user(db: Session, username: str, password: str):
    user = db.query(models.User).filter(
        models.User.username == username
    ).first()
    if not user:
        bcrypt.checkpw(b"dummy", _DUMMY_HASH)
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


# --- Dependencies ---

def get_current_user(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalid",
        )
    return user


def require_admin(current_user: models.User = Depends(get_current_user)):
    if current_user.role != Role.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return current_user


def require_fulfillment(current_user: models.User = Depends(get_current_user)):
    """Allow admin OR barista to mark orders complete. Used on PUT
    /orders/{id}/complete."""
    if current_user.role not in ORDER_FULFILLMENT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Order fulfillment role required",
        )
    return current_user


def require_dashboard(current_user: models.User = Depends(get_current_user)):
    """Allow admin OR viewer to read dashboard data (telemetry, orders list).
    Note: viewers can SEE telemetry but server-side mutation is still gated
    by the more restrictive deps above."""
    if current_user.role not in DASHBOARD_ROLES and current_user.role != Role.BARISTA:
        # Barista can also fetch the orders list (they need to see the queue),
        # so we widen this to include them. The "/dashboard" page itself is
        # gated separately at the auth-gate / template level.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dashboard access role required",
        )
    return current_user


# --- TOTP helpers ---

def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(
        name=username,
        issuer_name=TOTP_ISSUER,
    )


def totp_qr_data_uri(secret: str, username: str) -> str:
    uri = totp_provisioning_uri(secret, username)
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def verify_totp(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    try:
        return pyotp.TOTP(secret).verify(code, valid_window=TOTP_VALID_WINDOW)
    except Exception:
        return False


# --- Backup code helpers ---

_BACKUP_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _generate_one_backup_code() -> str:
    raw = "".join(secrets.choice(_BACKUP_ALPHABET) for _ in range(BACKUP_CODE_LENGTH))
    return f"{raw[:5]}-{raw[5:]}"


def generate_backup_codes() -> List[str]:
    return [_generate_one_backup_code() for _ in range(BACKUP_CODE_COUNT)]


def hash_backup_code(code: str) -> str:
    clean = code.replace("-", "").upper().encode("utf-8")
    return bcrypt.hashpw(clean, bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_backup_code_against_hash(supplied: str, code_hash: str) -> bool:
    if not supplied or not code_hash:
        return False
    clean = supplied.replace("-", "").upper().encode("utf-8")
    try:
        return bcrypt.checkpw(clean, code_hash.encode("utf-8"))
    except ValueError:
        return False


def consume_backup_code(db: Session, user: models.User, supplied: str) -> bool:
    from datetime import datetime, timezone

    unused = db.query(models.BackupCode).filter(
        models.BackupCode.user_id == user.id,
        models.BackupCode.used == False,  # noqa: E712
    ).all()

    for bc in unused:
        if verify_backup_code_against_hash(supplied, bc.code_hash):
            bc.used = True
            bc.used_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
            return True
    return False


# --- Bootstrap ---

def seed_initial_admin(username: str, password: str) -> None:
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
