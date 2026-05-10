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
from routers import orders, telemetry, auth, users, twofa, passkeys
from auth_utils import seed_initial_admin
from routers.auth import SESSION_LIFETIME_LONG
from roles import Role, DASHBOARD_ROLES, post_login_path

Base.metadata.create_all(bind=engine)
seed_initial_admin(ADMIN_USERNAME, ADMIN_PASSWORD)

app = FastAPI(title="CafeSync API")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- AUTH GATE ---
PUBLIC_PATHS = {
    "/health", "/login", "/logout", "/signup",
    "/login/2fa",
    "/passkey/login/begin",
    "/passkey/login/complete",
}

API_PREFIXES = ("/orders", "/telemetry", "/users", "/passkey")

# UI paths and which roles may reach them. Keys = path, values = set of roles.
# Anything not in this map is allowed for any authenticated user (e.g. /menu,
# /2fa/setup, /security).
RESTRICTED_UI_PATHS = {
    "/dashboard": DASHBOARD_ROLES | {Role.BARISTA},  # admin, viewer, barista (each gets its own template)
    "/": DASHBOARD_ROLES | {Role.BARISTA, Role.USER},  # everyone (we redirect by role below)
}


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

    # Per-path role restrictions for UI routes. /dashboard for users sends
    # them to /menu instead of 403 — better UX since /menu is THEIR home.
    if path == "/dashboard" and role == Role.USER:
        return RedirectResponse(url="/menu", status_code=302)

    return await call_next(request)


# --- TELEMETRY ---
TELEMETRY_EXCLUDED_PATHS = {
    "/health", "/dashboard", "/", "/login", "/logout", "/signup", "/menu",
    "/login/2fa", "/2fa/setup",
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


# --- SESSION MIDDLEWARE ---
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="cafesync_session",
    max_age=SESSION_LIFETIME_LONG,
    same_site="lax",
    https_only=False,  # Flip to True in production behind HTTPS.
)


app.include_router(auth.router)
app.include_router(twofa.router)
app.include_router(passkeys.router)
app.include_router(orders.router)
app.include_router(telemetry.router)
app.include_router(users.router)


@app.get("/dashboard", response_class=HTMLResponse, tags=["UI"])
async def render_dashboard(request: Request):
    """Renders the right dashboard for the user's role.
      admin   -> full dashboard.html
      viewer  -> same dashboard.html, controls hidden
      barista -> dashboard_barista.html (queue + serve only)
      user    -> redirected to /menu by auth-gate middleware
    """
    role = request.session.get("role", Role.USER)
    username = request.session.get("username", "")

    if role == Role.BARISTA:
        template = "dashboard_barista.html"
    else:
        # admin or viewer — same template, role determines what's visible
        template = "dashboard.html"

    return templates.TemplateResponse(
        request=request,
        name=template,
        context={"username": username, "role": role},
    )


@app.get("/menu", response_class=HTMLResponse, tags=["UI"])
async def render_menu(request: Request):
    """The customer-facing menu. Any authenticated user can browse;
    viewers see it without 'Place Order' buttons (handled in template + JS)."""
    role = request.session.get("role", Role.USER)
    username = request.session.get("username", "")
    return templates.TemplateResponse(
        request=request,
        name="menu.html",
        context={"username": username, "role": role},
    )


@app.get("/", include_in_schema=False)
def root_redirect(request: Request):
    """Send each role to the right home."""
    role = request.session.get("role")
    if not role:
        return RedirectResponse(url="/login")
    return RedirectResponse(url=post_login_path(role))


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "CafeSync Core"}
