# models.py
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from datetime import datetime, timezone
from database import Base
from roles import Role

# FIX: Use timezone-aware UTC datetimes via a lambda.
# datetime.utcnow() is deprecated in Python 3.12+ and returns naive datetimes,
# which can cause silent bugs with MSSQL datetime handling.
def _utcnow():
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

    Stores hashed passwords (bcrypt) — never plaintext.
    `role` controls dashboard access and per-endpoint permissions; see
    auth_utils.py for the dependencies that enforce it.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(16), nullable=False, default=Role.CUSTOMER, index=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
