# main.py
import time
from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session

from database import (
    engine, Base, SessionLocal,
    SESSION_SECRET, ADMIN_USERNAME, ADMIN_PASSWORD,
)
from models import SystemLog
import models
from routers import orders, telemetry, auth, users
from auth_utils import seed_initial_admin, require_staff
from routers.auth import SESSION_LIFETIME_LONG
from roles import Role, STAFF_ROLES

Base.metadata.create_all(bind=engine)

# Seed the bootstrap admin from .env if no admin exists yet.
seed_initial_admin(ADMIN_USERNAME, ADMIN_PASSWORD)

app = FastAPI(title="CafeSync Technical Monitoring API")

# --- UI CONFIGURATION ---
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- AUTH GATE ---
# Public paths: no authentication required.
PUBLIC_PATHS = {"/health", "/login", "/logout", "/signup"}

# Routes that should return JSON 401/403 instead of an HTML redirect when
# auth fails. These are the API surfaces consumed by app.js and external
# API clients.
API_PREFIXES = ("/orders", "/telemetry", "/users")

# Dashboard / UI paths that customers should NOT be able to reach. The
# auth gate redirects them to /login with a notice instead of letting
# them see a partial page or an error.
STAFF_ONLY_UI_PATHS = {"/dashboard", "/"}


@app.middleware("http")
async def auth_gate_middleware(request: Request, call_next):
    """Enforces authentication and broad role checks before the request
    reaches the route. Per-endpoint role enforcement (admin vs barista)
    is handled by the dependencies in the routers.

    Registered AFTER the telemetry middleware below, so in Starlette's
    last-registered-runs-first ordering, this runs FIRST. Failed-auth
    requests short-circuit before telemetry logs them, keeping the
    latency/error metrics clean.
    """
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

    # Per-session expiry. SessionMiddleware only supports one global
    # max_age, so we enforce the short window here.
    if user_id and expires_at and time.time() > expires_at:
        request.session.clear()
        user_id = None
        role = None

    # Defensive: a session with user_id but no role is corrupt (e.g. left
    # over from a pre-RBAC version). Treat it as unauthenticated so the
    # user can log in fresh, instead of getting stuck in a redirect loop.
    if user_id and not role:
        request.session.clear()
        user_id = None
        role = None

    if not user_id:
        if any(path.startswith(prefix) for prefix in API_PREFIXES):
            return JSONResponse(
                status_code=401,
                content={"detail": "Not authenticated"},
            )
        return RedirectResponse(url="/login", status_code=302)

    # Customer hitting a staff-only UI path: bounce them back to login.
    # We don't show them a 403 page since there's no UI for them anyway.
    if path in STAFF_ONLY_UI_PATHS and role not in STAFF_ROLES:
        return RedirectResponse(url="/login?signed_in=1", status_code=302)

    return await call_next(request)


# --- TELEMETRY ---
TELEMETRY_EXCLUDED_PATHS = {"/health", "/dashboard", "/", "/login", "/logout", "/signup"}

@app.middleware("http")
async def add_telemetry_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time_ms = (time.time() - start_time) * 1000

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
# Added LAST so it runs FIRST (Starlette wraps middleware in reverse).
# Sessions need to be available before the auth gate or telemetry try
# to read request.session.
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="cafesync_session",
    max_age=SESSION_LIFETIME_LONG,
    same_site="lax",
    https_only=False,  # Flip to True in production behind HTTPS.
)


app.include_router(auth.router)
app.include_router(orders.router)
app.include_router(telemetry.router)
app.include_router(users.router)


@app.get("/dashboard", response_class=HTMLResponse, tags=["UI"])
async def render_dashboard(request: Request):
    """Renders the operations dashboard.

    Two flavors:
      - admin:   full dashboard (telemetry + orders + user management)
      - barista: orders panel only (no telemetry, no user mgmt)

    Customers never reach here — the auth gate redirects them to /login.
    """
    role = request.session.get("role", Role.CUSTOMER)
    username = request.session.get("username", "")

    if role == Role.ADMIN:
        template = "dashboard.html"
    else:
        # Barista. Customers are filtered out by the auth gate before this point.
        template = "dashboard_barista.html"

    return templates.TemplateResponse(
        request=request,
        name=template,
        context={"username": username, "role": role},
    )


@app.get("/", include_in_schema=False)
def root_redirect():
    """Base URL: send to dashboard. Customers will get bounced from there
    by the auth gate to /login."""
    return RedirectResponse(url="/dashboard")


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "CafeSync Core"}
