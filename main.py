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
from roles import Role, STAFF_ROLES

Base.metadata.create_all(bind=engine)
seed_initial_admin(ADMIN_USERNAME, ADMIN_PASSWORD)

app = FastAPI(title="CafeSync Technical Monitoring API")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- AUTH GATE ---
# Public paths: /login/2fa is mid-login (no session yet). The passkey
# login endpoints are public because they ARE the authentication —
# verifying a passkey is what creates the session.
PUBLIC_PATHS = {
    "/health", "/login", "/logout", "/signup",
    "/login/2fa",
    "/passkey/login/begin",
    "/passkey/login/complete",
}

API_PREFIXES = ("/orders", "/telemetry", "/users", "/passkey")
STAFF_ONLY_UI_PATHS = {"/dashboard", "/"}


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

    if path in STAFF_ONLY_UI_PATHS and role not in STAFF_ROLES:
        return RedirectResponse(url="/login?signed_in=1", status_code=302)

    return await call_next(request)


# --- TELEMETRY ---
TELEMETRY_EXCLUDED_PATHS = {
    "/health", "/dashboard", "/", "/login", "/logout", "/signup",
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
# Added LAST so it runs FIRST (Starlette wraps middleware in reverse).
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
    role = request.session.get("role", Role.CUSTOMER)
    username = request.session.get("username", "")

    if role == Role.ADMIN:
        template = "dashboard.html"
    else:
        template = "dashboard_barista.html"

    return templates.TemplateResponse(
        request=request,
        name=template,
        context={"username": username, "role": role},
    )


@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/dashboard")


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "CafeSync Core"}
