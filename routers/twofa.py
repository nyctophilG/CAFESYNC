# routers/twofa.py
import time
from typing import Optional

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import models
from database import get_db
from auth_utils import (
    get_current_user, verify_password,
    generate_totp_secret, totp_qr_data_uri, verify_totp,
    generate_backup_codes, hash_backup_code, consume_backup_code,
)
from roles import post_login_path
from security import rate_limiter

router = APIRouter(tags=["Two-Factor Auth"])
templates = Jinja2Templates(directory="templates")

SESSION_LIFETIME_SHORT = 8 * 60 * 60
SESSION_LIFETIME_LONG = 30 * 24 * 60 * 60

PENDING_LOGIN_TTL = 5 * 60


# =======================================================================
# Setup flow
# =======================================================================

@router.get("/2fa/setup", response_class=HTMLResponse, include_in_schema=False)
async def setup_page(
    request: Request,
    current_user: models.User = Depends(get_current_user),
):
    pending_secret = request.session.get("pending_totp_secret")
    qr_uri = None
    if pending_secret and not current_user.totp_enabled:
        qr_uri = totp_qr_data_uri(pending_secret, current_user.username)

    backup_remaining = 0
    if current_user.totp_enabled:
        backup_remaining = sum(1 for c in current_user.backup_codes if not c.used)

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
    if current_user.totp_enabled:
        raise HTTPException(status_code=400, detail="2FA is already enabled.")
    secret = generate_totp_secret()
    request.session["pending_totp_secret"] = secret
    return RedirectResponse(url="/2fa/setup", status_code=303)


@router.post("/2fa/confirm", include_in_schema=False)
@rate_limiter.limit("5/minute")
async def confirm_setup(
    request: Request,
    code: str = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    pending = request.session.get("pending_totp_secret")
    if not pending:
        raise HTTPException(status_code=400, detail="No setup in progress.")

    if not verify_totp(pending, code):
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

    current_user.totp_secret = pending
    current_user.totp_enabled = True
    db.commit()
    request.session.pop("pending_totp_secret", None)

    plaintext_codes = generate_backup_codes()
    for plain in plaintext_codes:
        db.add(models.BackupCode(user_id=current_user.id, code_hash=hash_backup_code(plain)))
    db.commit()

    request.session["fresh_backup_codes"] = plaintext_codes
    return RedirectResponse(url="/2fa/setup", status_code=303)


@router.post("/2fa/disable", include_in_schema=False)
async def disable_2fa(
    request: Request,
    password: str = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
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
    if not current_user.totp_enabled:
        raise HTTPException(status_code=400, detail="2FA is not enabled.")

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
# Challenge flow
# =======================================================================

@router.get("/login/2fa", response_class=HTMLResponse, include_in_schema=False)
async def challenge_page(request: Request, db: Session = Depends(get_db)):
    pending_id = request.session.get("pending_user_id")
    pending_at = request.session.get("pending_at")

    if not pending_id or not pending_at or time.time() - pending_at > PENDING_LOGIN_TTL:
        request.session.pop("pending_user_id", None)
        request.session.pop("pending_at", None)
        request.session.pop("pending_remember_me", None)
        return RedirectResponse(url="/login", status_code=303)

    user = db.query(models.User).filter(models.User.id == pending_id).first()
    if not user:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="twofa_challenge.html",
        context={"username": user.username, "error": None},
    )


@router.post("/login/2fa", response_class=HTMLResponse, include_in_schema=False)
@rate_limiter.limit("5/minute")
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
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    code = code.strip()

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

    return RedirectResponse(url=post_login_path(user.role), status_code=303)
