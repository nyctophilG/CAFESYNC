# routers/twofa.py
"""Two-factor authentication endpoints.

Two distinct flows live in this file:

  Setup flow  (logged-in user enabling 2FA on their account)
    GET  /2fa/setup       -> Renders the page that includes the QR code.
    POST /2fa/begin       -> Generates a fresh secret, stores it as PENDING
                             (in session, NOT on the User row yet), returns
                             the QR data URI.
    POST /2fa/confirm     -> User enters first code. If valid, we move the
                             secret from session to User.totp_secret, flip
                             totp_enabled=True, generate backup codes.
    POST /2fa/disable     -> Wipes totp_secret, totp_enabled, backup codes.
                             Requires current password to prevent a session
                             hijacker from disabling 2FA without the password.
    POST /2fa/regen-codes -> Invalidates all existing backup codes and
                             returns a fresh batch.

  Challenge flow (during login, after password but before full session)
    GET  /login/2fa       -> Page where the user enters TOTP or backup code.
    POST /login/2fa       -> Verify and complete login, OR re-render with error.

The login handler in routers/auth.py handles the password step and decides
whether to redirect here based on user.totp_enabled.
"""
import time
from typing import Optional

from fastapi import APIRouter, Request, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import models
from database import get_db
from auth_utils import (
    get_current_user, verify_password,
    generate_totp_secret, totp_qr_data_uri, verify_totp,
    generate_backup_codes, hash_backup_code, consume_backup_code,
)
from roles import STAFF_ROLES

router = APIRouter(tags=["Two-Factor Auth"])
templates = Jinja2Templates(directory="templates")

# Session lifetimes — kept in sync with routers/auth.py
SESSION_LIFETIME_SHORT = 8 * 60 * 60
SESSION_LIFETIME_LONG = 30 * 24 * 60 * 60

# How long the password-only "pending" state may survive before forcing
# the user to start over. 5 minutes is plenty to fish out a phone and
# read a TOTP code.
PENDING_LOGIN_TTL = 5 * 60


# =======================================================================
# Setup flow (authenticated user managing their own 2FA)
# =======================================================================

@router.get("/2fa/setup", response_class=HTMLResponse, include_in_schema=False)
async def setup_page(
    request: Request,
    current_user: models.User = Depends(get_current_user),
):
    """Renders the 2FA settings page. Behavior depends on current state:
      - 2FA off: show "Enable 2FA" button.
      - Setup in progress: show QR + code-confirm form.
      - 2FA on: show "Disable 2FA" + "Regenerate backup codes".
    """
    pending_secret = request.session.get("pending_totp_secret")
    qr_uri = None
    if pending_secret and not current_user.totp_enabled:
        qr_uri = totp_qr_data_uri(pending_secret, current_user.username)

    # Count remaining backup codes (only relevant if 2FA is on).
    backup_remaining = 0
    if current_user.totp_enabled:
        backup_remaining = sum(1 for c in current_user.backup_codes if not c.used)

    # If there are fresh codes to display once, pull them out of the session.
    fresh_codes = request.session.pop("fresh_backup_codes", None)

    return templates.TemplateResponse(
        request=request,
        name="twofa_setup.html",
        context={
            "user": current_user,
            "qr_data_uri": qr_uri,
            "pending_secret": pending_secret,
            "backup_remaining": backup_remaining,
            "fresh_codes": fresh_codes,
        },
    )


@router.post("/2fa/begin", include_in_schema=False)
async def begin_setup(
    request: Request,
    current_user: models.User = Depends(get_current_user),
):
    """Generates a fresh TOTP secret and stores it in the SESSION (not on
    the User row) until confirmed. This prevents a half-completed setup
    from breaking login: until the user proves they have the secret on
    their phone, password-only login still works.
    """
    if current_user.totp_enabled:
        raise HTTPException(status_code=400, detail="2FA is already enabled.")

    secret = generate_totp_secret()
    request.session["pending_totp_secret"] = secret
    return RedirectResponse(url="/2fa/setup", status_code=303)


@router.post("/2fa/confirm", include_in_schema=False)
async def confirm_setup(
    request: Request,
    code: str = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """User has scanned the QR and is entering their first code. Verify
    against the pending secret. On success, persist the secret, generate
    backup codes, and stash them in session for one-shot display."""
    pending = request.session.get("pending_totp_secret")
    if not pending:
        raise HTTPException(status_code=400, detail="No setup in progress.")

    if not verify_totp(pending, code):
        # Re-render the setup page with an error — the secret stays pending.
        qr_uri = totp_qr_data_uri(pending, current_user.username)
        return templates.TemplateResponse(
            request=request,
            name="twofa_setup.html",
            context={
                "user": current_user,
                "qr_data_uri": qr_uri,
                "pending_secret": pending,
                "backup_remaining": 0,
                "fresh_codes": None,
                "error": "That code didn't match. Make sure your phone's clock is correct and try again.",
            },
            status_code=400,
        )

    # Promote pending secret to permanent.
    current_user.totp_secret = pending
    current_user.totp_enabled = True
    db.commit()
    request.session.pop("pending_totp_secret", None)

    # Generate backup codes. Show plaintext exactly once, store hashes.
    plaintext_codes = generate_backup_codes()
    for plain in plaintext_codes:
        db.add(models.BackupCode(user_id=current_user.id, code_hash=hash_backup_code(plain)))
    db.commit()

    # Stash plaintext in session so the redirect target can display them.
    # We pop them on next render so they only show once.
    request.session["fresh_backup_codes"] = plaintext_codes
    return RedirectResponse(url="/2fa/setup", status_code=303)


@router.post("/2fa/disable", include_in_schema=False)
async def disable_2fa(
    request: Request,
    password: str = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Disabling 2FA requires re-entering the password — defense in depth
    in case a session is hijacked, the attacker can't simply turn off 2FA.

    Wipes the secret, all backup codes, and the enabled flag.
    """
    if not verify_password(password, current_user.hashed_password):
        return templates.TemplateResponse(
            request=request,
            name="twofa_setup.html",
            context={
                "user": current_user,
                "qr_data_uri": None,
                "pending_secret": None,
                "backup_remaining": sum(1 for c in current_user.backup_codes if not c.used),
                "fresh_codes": None,
                "error": "Password incorrect — 2FA was not disabled.",
            },
            status_code=400,
        )

    current_user.totp_enabled = False
    current_user.totp_secret = None
    # Cascade delete handles backup_codes, but be explicit:
    db.query(models.BackupCode).filter(
        models.BackupCode.user_id == current_user.id
    ).delete()
    db.commit()
    return RedirectResponse(url="/2fa/setup", status_code=303)


@router.post("/2fa/regen-codes", include_in_schema=False)
async def regen_backup_codes(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Invalidate all existing codes (used or not) and issue a fresh set."""
    if not current_user.totp_enabled:
        raise HTTPException(status_code=400, detail="2FA is not enabled.")

    # Wipe old codes — used or not. They're useless now anyway.
    db.query(models.BackupCode).filter(
        models.BackupCode.user_id == current_user.id
    ).delete()
    db.commit()

    plaintext_codes = generate_backup_codes()
    for plain in plaintext_codes:
        db.add(models.BackupCode(user_id=current_user.id, code_hash=hash_backup_code(plain)))
    db.commit()

    request.session["fresh_backup_codes"] = plaintext_codes
    return RedirectResponse(url="/2fa/setup", status_code=303)


# =======================================================================
# Challenge flow (during login, after password verification)
# =======================================================================

def _post_login_redirect(role: str) -> str:
    """Where to land a user after fully completing login (password + 2FA)."""
    if role in STAFF_ROLES:
        return "/dashboard"
    return "/login?signed_in=1"


@router.get("/login/2fa", response_class=HTMLResponse, include_in_schema=False)
async def challenge_page(request: Request, db: Session = Depends(get_db)):
    pending_id = request.session.get("pending_user_id")
    pending_at = request.session.get("pending_at")

    # If no pending login or it's expired, send them back to /login.
    if not pending_id or not pending_at or time.time() - pending_at > PENDING_LOGIN_TTL:
        request.session.pop("pending_user_id", None)
        request.session.pop("pending_at", None)
        request.session.pop("pending_remember_me", None)
        return RedirectResponse(url="/login", status_code=303)

    user = db.query(models.User).filter(models.User.id == pending_id).first()
    if not user:
        # User deleted between password-step and 2FA step. Punt back to login.
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="twofa_challenge.html",
        context={"username": user.username, "error": None},
    )


@router.post("/login/2fa", response_class=HTMLResponse, include_in_schema=False)
async def challenge_submit(
    request: Request,
    code: str = Form(...),
    use_backup: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    pending_id = request.session.get("pending_user_id")
    pending_at = request.session.get("pending_at")
    remember_me = request.session.get("pending_remember_me", False)

    if not pending_id or not pending_at or time.time() - pending_at > PENDING_LOGIN_TTL:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    user = db.query(models.User).filter(models.User.id == pending_id).first()
    if not user or not user.totp_enabled:
        # Should never happen if /login routed correctly, but fail closed.
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    # Trim the code; user may have entered with whitespace.
    code = code.strip()

    # Try backup code first if the checkbox/toggle is set; otherwise TOTP.
    # (We could try both regardless and skip the toggle, but having the
    # explicit user intent makes the rate-limit story cleaner later.)
    verified = False
    if use_backup:
        verified = consume_backup_code(db, user, code)
    else:
        verified = verify_totp(user.totp_secret, code)

    if not verified:
        return templates.TemplateResponse(
            request=request,
            name="twofa_challenge.html",
            context={
                "username": user.username,
                "error": "Invalid code. Try again, or use a backup code.",
            },
            status_code=401,
        )

    # Successful 2FA. Promote the pending session to a real one.
    request.session.pop("pending_user_id", None)
    request.session.pop("pending_at", None)
    request.session.pop("pending_remember_me", None)

    request.session["user_id"] = user.id
    request.session["username"] = user.username
    request.session["role"] = user.role

    if remember_me:
        request.session["expires_at"] = int(time.time()) + SESSION_LIFETIME_LONG
    else:
        request.session["expires_at"] = int(time.time()) + SESSION_LIFETIME_SHORT

    return RedirectResponse(url=_post_login_redirect(user.role), status_code=303)
