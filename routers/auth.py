# routers/auth.py
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from auth_utils import authenticate_admin

router = APIRouter(tags=["Authentication"])
templates = Jinja2Templates(directory="templates")

# Session lifetimes (seconds)
SESSION_LIFETIME_SHORT = 8 * 60 * 60        # 8 hours
SESSION_LIFETIME_LONG = 30 * 24 * 60 * 60   # 30 days


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request):
    # If already logged in, send them straight to the dashboard.
    if request.session.get("user_id"):
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": None},
    )


@router.post("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    remember_me: str | None = Form(None),
    db: Session = Depends(get_db),
):
    user = authenticate_admin(db, username.strip(), password)
    if not user:
        # Re-render with a generic error — don't disclose which field was wrong.
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Invalid username or password."},
            status_code=401,
        )

    # Successful login — store minimal identifiers in the signed session cookie.
    request.session["user_id"] = user.id
    request.session["username"] = user.username
    # Starlette's SessionMiddleware uses a single max_age for the cookie, so we
    # toggle it per-request by writing the desired lifetime into the session
    # itself and reading it from a custom middleware layer. Simpler approach:
    # rely on max_age set on SessionMiddleware (long), and store an explicit
    # expiry timestamp to enforce the short window when remember_me is off.
    import time
    if remember_me:
        request.session["expires_at"] = int(time.time()) + SESSION_LIFETIME_LONG
    else:
        request.session["expires_at"] = int(time.time()) + SESSION_LIFETIME_SHORT

    return RedirectResponse(url="/dashboard", status_code=302)


@router.post("/logout", include_in_schema=False)
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)


@router.get("/logout", include_in_schema=False)
async def logout_get(request: Request):
    # Allow GET /logout too, since a plain anchor tag in the navbar is the
    # simplest UI. CSRF risk is minimal because logging someone out is a
    # nuisance, not a privilege escalation.
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)
