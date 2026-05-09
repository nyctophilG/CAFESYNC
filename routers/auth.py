# routers/auth.py
import time
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

import models
from database import get_db
from auth_utils import authenticate_user, hash_password, BCRYPT_MAX_BYTES
from roles import Role, STAFF_ROLES

router = APIRouter(tags=["Authentication"])
templates = Jinja2Templates(directory="templates")

# Session lifetimes (kept in sync with routers/twofa.py)
SESSION_LIFETIME_SHORT = 8 * 60 * 60
SESSION_LIFETIME_LONG = 30 * 24 * 60 * 60

# Minimum password length for new accounts.
MIN_PASSWORD_LENGTH = 8


def _post_login_redirect(role: str) -> str:
    if role in STAFF_ROLES:
        return "/dashboard"
    return "/login?signed_in=1"


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request, signed_in: int = 0):
    user_id = request.session.get("user_id")
    role = request.session.get("role")
    if user_id and role in STAFF_ROLES:
        return RedirectResponse(url="/dashboard", status_code=302)

    if user_id and not role:
        # Corrupt session — clear and fall through to render login form.
        request.session.clear()

    notice = None
    if signed_in and user_id:
        notice = (
            "You're signed in as a customer. The dashboard is staff-only, "
            "but you can place orders via the API."
        )
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": None, "notice": notice},
    )


@router.post("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    remember_me: str | None = Form(None),
    db: Session = Depends(get_db),
):
    user = authenticate_user(db, username.strip(), password)
    if not user:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Invalid username or password.", "notice": None},
            status_code=401,
        )

    # Password verified. Branch on whether 2FA is enabled.
    if user.totp_enabled:
        # Stash a "pending" identity in the session and redirect to the
        # challenge page. Crucially: we DO NOT set user_id yet, so the
        # auth_gate middleware still treats this as unauthenticated for
        # any other route.
        request.session.clear()  # wipe any prior partial state
        request.session["pending_user_id"] = user.id
        request.session["pending_at"] = int(time.time())
        request.session["pending_remember_me"] = bool(remember_me)
        return RedirectResponse(url="/login/2fa", status_code=302)

    # No 2FA — log in immediately.
    request.session["user_id"] = user.id
    request.session["username"] = user.username
    request.session["role"] = user.role

    if remember_me:
        request.session["expires_at"] = int(time.time()) + SESSION_LIFETIME_LONG
    else:
        request.session["expires_at"] = int(time.time()) + SESSION_LIFETIME_SHORT

    return RedirectResponse(url=_post_login_redirect(user.role), status_code=302)


@router.get("/signup", response_class=HTMLResponse, include_in_schema=False)
async def signup_page(request: Request):
    user_id = request.session.get("user_id")
    role = request.session.get("role")
    if user_id and role in STAFF_ROLES:
        return RedirectResponse(url="/dashboard", status_code=302)
    if user_id:
        return RedirectResponse(url="/login?signed_in=1", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="signup.html",
        context={"error": None},
    )


@router.post("/signup", response_class=HTMLResponse, include_in_schema=False)
async def signup_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    username = username.strip()

    error = None
    if len(username) < 3:
        error = "Username must be at least 3 characters."
    elif len(password) < MIN_PASSWORD_LENGTH:
        error = f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    elif len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        error = f"Password must be at most {BCRYPT_MAX_BYTES} bytes when encoded."

    if error:
        return templates.TemplateResponse(
            request=request,
            name="signup.html",
            context={"error": error},
            status_code=400,
        )

    new_user = models.User(
        username=username,
        hashed_password=hash_password(password),
        role=Role.CUSTOMER,
    )
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return templates.TemplateResponse(
            request=request,
            name="signup.html",
            context={"error": "That username is already taken."},
            status_code=409,
        )
    db.refresh(new_user)

    # Auto-login. Customers don't have 2FA at signup time, so no challenge step.
    request.session["user_id"] = new_user.id
    request.session["username"] = new_user.username
    request.session["role"] = new_user.role
    request.session["expires_at"] = int(time.time()) + SESSION_LIFETIME_SHORT

    return RedirectResponse(url=_post_login_redirect(new_user.role), status_code=302)


@router.post("/logout", include_in_schema=False)
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)


@router.get("/logout", include_in_schema=False)
async def logout_get(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)
