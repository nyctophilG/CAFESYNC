# main.py
import time
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from database import (
    engine, Base, SessionLocal,
    SESSION_SECRET, ADMIN_USERNAME, ADMIN_PASSWORD,
)
from models import SystemLog
import models
from routers import orders, telemetry, auth
from auth_utils import seed_initial_admin
from routers.auth import SESSION_LIFETIME_LONG

Base.metadata.create_all(bind=engine)

# Seed the bootstrap admin account from .env if no admin exists yet.
# Idempotent — see auth_utils.seed_initial_admin for the rationale.
seed_initial_admin(ADMIN_USERNAME, ADMIN_PASSWORD)

app = FastAPI(title="CafeSync Technical Monitoring API")

# --- UI CONFIGURATION ---
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- AUTH GATE ---
# Paths that don't require authentication. Everything else is protected.
# Note: /static is handled via prefix match below, not in this set.
PUBLIC_PATHS = {"/health", "/login", "/logout"}

# Routes that should return JSON 401 instead of an HTML redirect when
# unauthenticated. These are the API surfaces consumed by app.js.
API_PREFIXES = ("/orders", "/telemetry")


@app.middleware("http")
async def auth_gate_middleware(request: Request, call_next):
    """Enforce authentication on all routes except the public allowlist.

    Registered AFTER the telemetry middleware below, so in Starlette's
    last-registered-runs-first ordering, this runs FIRST. That means
    failed-auth requests short-circuit before telemetry logs them,
    keeping the latency/error metrics clean.
    """
    path = request.url.path

    # Allow public paths and static assets through unconditionally.
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

    # Enforce per-session expiry (independent of the cookie's max_age, so we
    # can offer a remember-me toggle even though SessionMiddleware only
    # supports one global max_age).
    if user_id and expires_at and time.time() > expires_at:
        request.session.clear()
        user_id = None

    if not user_id:
        # JSON 401 for API routes so app.js can react; redirect for HTML.
        if any(path.startswith(prefix) for prefix in API_PREFIXES):
            return JSONResponse(
                status_code=401,
                content={"detail": "Not authenticated"},
            )
        return RedirectResponse(url="/login", status_code=302)

    return await call_next(request)


# --- TELEMETRY ---
# FIX: Middleware must be registered BEFORE routers so it wraps all routes.
# FIX: Filter out noise from health checks, dashboard UI, and static assets.
TELEMETRY_EXCLUDED_PATHS = {"/health", "/dashboard", "/", "/login", "/logout"}

@app.middleware("http")
async def add_telemetry_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time_ms = (time.time() - start_time) * 1000

    # Skip logging for excluded paths and all static file requests
    if (
        request.url.path not in TELEMETRY_EXCLUDED_PATHS
        and not request.url.path.startswith("/static")
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


# --- SESSION MIDDLEWARE ---
# Must be added LAST so it runs FIRST in the stack (Starlette wraps middleware
# in reverse registration order). Sessions need to be available before the
# auth gate or telemetry try to read request.session.
#
# https_only=False for local dev; flip to True in production behind HTTPS.
# max_age is set to the long lifetime — the auth gate enforces the short
# lifetime per-session via the "expires_at" key when remember_me is off.
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="cafesync_session",
    max_age=SESSION_LIFETIME_LONG,
    same_site="lax",
    https_only=False,
)


app.include_router(auth.router)
app.include_router(orders.router)
app.include_router(telemetry.router)

@app.get("/dashboard", response_class=HTMLResponse, tags=["UI"])
async def render_dashboard(request: Request):
    """Renders the HTML monitoring dashboard."""
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"username": request.session.get("username", "admin")},
    )

@app.get("/", include_in_schema=False)
def root_redirect():
    """Automatically redirects the base URL to the Operations Dashboard."""
    return RedirectResponse(url="/dashboard")

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "CafeSync Core"}
