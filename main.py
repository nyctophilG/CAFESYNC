# main.py
import os
import time

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from slowapi.errors import RateLimitExceeded

from database import (
    engine, Base, SessionLocal,
    SESSION_SECRET, ADMIN_USERNAME, ADMIN_PASSWORD,
)
from models import SystemLog
import models
from routers import orders, telemetry, auth, users, twofa, passkeys
from auth_utils import seed_initial_admin
from routers.auth import SESSION_LIFETIME_LONG
from roles import Role, DASHBOARD_ROLES, post_login_path
from security import (
    rate_limiter,
    add_security_headers,
    configure_error_handlers,
    get_csrf_token,
    HTTPS_ONLY,
)

Base.metadata.create_all(bind=engine)
seed_initial_admin(ADMIN_USERNAME, ADMIN_PASSWORD)

app = FastAPI(title="CafeSync API")

# Attach the rate limiter to the app so SlowAPI's decorators work.
app.state.limiter = rate_limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Return a generic 429 when someone hits a rate limit.
    Doesn't reveal which limit they hit or how to bypass it."""
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please wait a moment and try again."},
    )


# Generic error handler — hides stack traces in production.
configure_error_handlers(app)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# --- AUTH GATE ---
PUBLIC_PATHS = {
    "/health", "/login", "/logout", "/signup",
    "/login/2fa",
    "/passkey/login/begin",
    "/passkey/login/complete",
    "/csrf-token",  # JS needs to fetch this before authed requests
}

API_PREFIXES = ("/orders", "/telemetry", "/users", "/passkey")


@app.middleware("http")
async def auth_gate_middleware(request: Request, call_next):
    """Auth gating. Per-endpoint role checks happen in the routers."""
    path = request.url.path

    is_public = (
        path in PUBLIC_PATHS
        or path.startswith("/static")
        or path == "/docs"
        or path == "/openapi.json"
    )
    if is_public:
        return await call_next(request)

    user_id = request.session.get("user_id")
    expires_at = request.session.get("expires_at")
    role = request.session.get("role")

    if user_id and expires_at and time.time() > expires_at:
        request.session.clear()
        user_id = None
        role = None

    if user_id and not role:
        request.session.clear()
        user_id = None
        role = None

    if not user_id:
        if any(path.startswith(prefix) for prefix in API_PREFIXES):
            return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
        return RedirectResponse(url="/login", status_code=302)

    if path == "/dashboard" and role == Role.USER:
        return RedirectResponse(url="/menu", status_code=302)

    return await call_next(request)


# --- TELEMETRY ---
TELEMETRY_EXCLUDED_PATHS = {
    "/health", "/dashboard", "/", "/login", "/logout", "/signup", "/menu",
    "/login/2fa", "/2fa/setup", "/csrf-token",
}


@app.middleware("http")
async def add_telemetry_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time_ms = (time.time() - start_time) * 1000

    if (
        request.url.path not in TELEMETRY_EXCLUDED_PATHS
        and not request.url.path.startswith("/static")
        and not request.url.path.startswith("/2fa/")
        and not request.url.path.startswith("/passkey/")
    ):
        db = SessionLocal()
        try:
            log_entry = SystemLog(
                endpoint=request.url.path,
                method=request.method,
                status_code=response.status_code,
                response_time_ms=process_time_ms
            )
            db.add(log_entry)
            db.commit()
        finally:
            db.close()

    return response


# --- SECURITY HEADERS ---
# Runs on every response. Cheap insurance against XSS, clickjacking, MIME
# sniffing, leaked referrers, HTTPS downgrade.
app.middleware("http")(add_security_headers)


# --- SESSION MIDDLEWARE ---
# https_only and samesite are tightened in production via HTTPS_ONLY env var.
# Cookies are signed with SESSION_SECRET (itsdangerous library).
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="cafesync_session",
    max_age=SESSION_LIFETIME_LONG,
    same_site="strict" if HTTPS_ONLY else "lax",
    https_only=HTTPS_ONLY,
)


app.include_router(auth.router)
app.include_router(twofa.router)
app.include_router(passkeys.router)
app.include_router(orders.router)
app.include_router(telemetry.router)
app.include_router(users.router)


# --- UI routes ---

@app.get("/dashboard", response_class=HTMLResponse, tags=["UI"])
async def render_dashboard(request: Request):
    """Renders the right dashboard for the user's role."""
    role = request.session.get("role", Role.USER)
    username = request.session.get("username", "")

    if role == Role.BARISTA:
        template = "dashboard_barista.html"
    else:
        template = "dashboard.html"

    return templates.TemplateResponse(
        request=request,
        name=template,
        context={
            "username": username,
            "role": role,
            "csrf_token": get_csrf_token(request),
        },
    )


@app.get("/menu", response_class=HTMLResponse, tags=["UI"])
async def render_menu(request: Request):
    role = request.session.get("role", Role.USER)
    username = request.session.get("username", "")
    return templates.TemplateResponse(
        request=request,
        name="menu.html",
        context={
            "username": username,
            "role": role,
            "csrf_token": get_csrf_token(request),
        },
    )


@app.get("/", include_in_schema=False)
def root_redirect(request: Request):
    role = request.session.get("role")
    if not role:
        return RedirectResponse(url="/login")
    return RedirectResponse(url=post_login_path(role))


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "CafeSync Core"}


@app.get("/csrf-token", tags=["Security"])
async def get_csrf_token_endpoint(request: Request):
    """JS clients fetch this once at page load to get a CSRF token they
    can include in subsequent state-changing requests as X-CSRF-Token.

    Public path (no auth) so even the /login page can grab a token before
    the user has a session — useful if we ever protect /login with CSRF
    (we don't currently, since brute-force is handled by rate limit).
    """
    return {"csrf_token": get_csrf_token(request)}
