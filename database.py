# database.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

def _require_env(key: str) -> str:
    """Fail loudly at startup if a required env var is missing."""
    value = os.getenv(key)
    if not value:
        raise RuntimeError(
            f"Required environment variable '{key}' is not set. "
            "Please configure your .env file before starting the server."
        )
    return value

# --- Database (SQLite) ---
DB_PATH = os.getenv("DB_PATH", "./cafesync.db")
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

# --- Required auth config ---
SESSION_SECRET = _require_env("SESSION_SECRET")
ADMIN_USERNAME = _require_env("ADMIN_USERNAME")
ADMIN_PASSWORD = _require_env("ADMIN_PASSWORD")

# --- WebAuthn / Passkeys config ---
# RP_ID is the domain passkeys are bound to. Must match the host the user
# sees in their browser (no scheme, no port). Examples:
#   localhost                -> for local dev
#   cafesync.fly.dev         -> for production on fly.io
#   yourdomain.com           -> for a custom domain
#
# A passkey registered on one RP_ID will NOT work on another. So local-dev
# passkeys are separate from production passkeys (which is fine, just
# something to know on demo day — register a fresh passkey after deploy).
RP_ID = os.getenv("RP_ID", "localhost")

# RP_NAME shows in the OS prompt: "Save passkey for CafeSync?"
RP_NAME = os.getenv("RP_NAME", "CafeSync")

# ORIGIN is the full URL (with scheme + port) the browser is loading from.
# WebAuthn verifies the origin in the assertion matches what we expect, so
# this must be exact. Spec allows multiple origins (e.g. http://localhost
# AND http://127.0.0.1) — we accept both for dev convenience.
_DEFAULT_ORIGINS = "http://localhost:8000,http://127.0.0.1:8000"
EXPECTED_ORIGINS = [
    o.strip() for o in os.getenv("WEBAUTHN_ORIGINS", _DEFAULT_ORIGINS).split(",")
    if o.strip()
]

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    # SQLite multi-thread quirk: standard fix for FastAPI's threadpool model.
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
