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
from roles import Role, post_login_path
from security import rate_limiter, is_localhost

router = APIRouter(tags=["Authentication"])
templates = Jinja2Templates(directory="templates")

SESSION_LIFETIME_SHORT = 8 * 60 * 60
SESSION_LIFETIME_LONG = 30 * 24 * 60 * 60

MIN_PASSWORD_LENGTH = 8


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request):
    user_id = request.session.get("user_id")
    role = request.session.get("role")
    if user_id and role:
        return RedirectResponse(url=post_login_path(role), status_code=302)

    if user_id and not role:
        request.session.clear()

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": None, "notice": None},
    )


# Rate limit: 5 login attempts per minute per IP. Stops brute force without
# being too aggressive against a clumsy real user retrying their password.
@router.post("/login", response_class=HTMLResponse, include_in_schema=False)
@rate_limiter.limit("5/minute", exempt_when=is_localhost)
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

    if user.totp_enabled:
        request.session.clear()
        request.session["pending_user_id"] = user.id
        request.session["pending_at"] = int(time.time())
        request.session["pending_remember_me"] = bool(remember_me)
        return RedirectResponse(url="/login/2fa", status_code=302)

    request.session["user_id"] = user.id
    request.session["username"] = user.username
    request.session["role"] = user.role

    if remember_me:
        request.session["expires_at"] = int(time.time()) + SESSION_LIFETIME_LONG
    else:
        request.session["expires_at"] = int(time.time()) + SESSION_LIFETIME_SHORT

    return RedirectResponse(url=post_login_path(user.role), status_code=302)


@router.get("/signup", response_class=HTMLResponse, include_in_schema=False)
async def signup_page(request: Request):
    user_id = request.session.get("user_id")
    role = request.session.get("role")
    if user_id and role:
        return RedirectResponse(url=post_login_path(role), status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="signup.html",
        context={"error": None},
    )


# Rate limit: 3 signups per minute per IP. Slows mass account creation.
@router.post("/signup", response_class=HTMLResponse, include_in_schema=False)
@rate_limiter.limit("3/minute", exempt_when=is_localhost)
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
        role=Role.USER,
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

    request.session["user_id"] = new_user.id
    request.session["username"] = new_user.username
    request.session["role"] = new_user.role
    request.session["expires_at"] = int(time.time()) + SESSION_LIFETIME_SHORT

    return RedirectResponse(url=post_login_path(new_user.role), status_code=302)


@router.post("/logout", include_in_schema=False)
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)


@router.get("/logout", include_in_schema=False)
async def logout_get(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)
