# models.py
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean, ForeignKey, LargeBinary,
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from database import Base
from roles import Role


def _utcnow():
    """Use timezone-aware UTC datetimes. datetime.utcnow() is deprecated in
    Python 3.12+ and returns naive datetimes."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SystemLog(Base):
    """Pod 2: Technical Monitoring Telemetry Table"""
    __tablename__ = "technical_logs"

    id = Column(Integer, primary_key=True, index=True)
    endpoint = Column(String(255), nullable=False)
    method = Column(String(10), nullable=False)
    status_code = Column(Integer, nullable=False)
    response_time_ms = Column(Float, nullable=False)
    timestamp = Column(DateTime(timezone=True), default=_utcnow)


class Order(Base):
    """Pod 1: Cafe Business Logic Table"""
    __tablename__ = "cafe_orders"

    id = Column(Integer, primary_key=True, index=True)
    item_name = Column(String(100), nullable=False)
    quantity = Column(Integer, nullable=False)
    is_completed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)


class User(Base):
    """Unified user table for all roles (admin, barista, customer).

    Auth columns:
      - hashed_password: bcrypt
      - totp_secret / totp_enabled: TOTP via authenticator app
      - email: optional, kept for future email-based features
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(16), nullable=False, default=Role.CUSTOMER, index=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    email = Column(String(255), nullable=True, unique=True, index=True)
    email_verified = Column(Boolean, default=False, nullable=False)

    totp_secret = Column(String(64), nullable=True)
    totp_enabled = Column(Boolean, default=False, nullable=False)

    backup_codes = relationship(
        "BackupCode",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    passkeys = relationship(
        "Passkey",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    @property
    def has_2fa(self) -> bool:
        """Whether this account currently requires a second factor at login."""
        return bool(self.totp_enabled)


class BackupCode(Base):
    """Single-use recovery codes generated when TOTP is enabled."""
    __tablename__ = "backup_codes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code_hash = Column(String(255), nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    used_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="backup_codes")


class Passkey(Base):
    """WebAuthn / FIDO2 passkey credentials.

    A user can have multiple passkeys (e.g. one per device). The `name`
    column is a human-readable label the user assigns at registration time
    so they can manage which devices are enrolled.

    Stored fields are exactly what the webauthn library needs for
    verification:
      - credential_id: the unique ID issued by the authenticator. Used as
        the lookup key during login.
      - public_key: the COSE-encoded public key. Bytes, not human-readable.
      - sign_count: a monotonically-increasing counter the authenticator
        bumps on each use. Helps detect cloned credentials.
    """
    __tablename__ = "passkeys"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # credential_id is binary; we store base64url-encoded for portability
    # and easy debugging. The webauthn library returns it as bytes; we
    # encode/decode at the boundary.
    credential_id = Column(String(512), unique=True, nullable=False, index=True)
    public_key = Column(LargeBinary, nullable=False)
    sign_count = Column(Integer, default=0, nullable=False)
    name = Column(String(64), nullable=False, default="Unnamed device")
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="passkeys")
