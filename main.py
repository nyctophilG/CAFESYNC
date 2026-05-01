# main.py
import time
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from database import engine, Base, SessionLocal
from models import SystemLog
import models
from routers import orders, telemetry

Base.metadata.create_all(bind=engine)

app = FastAPI(title="CafeSync Technical Monitoring API")

# --- UI CONFIGURATION (NEW) ---
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/dashboard", response_class=HTMLResponse, tags=["UI"])
async def render_dashboard(request: Request):
    """Renders the HTML monitoring dashboard."""
    # Enforcing strict keyword arguments to satisfy modern Starlette signatures
    return templates.TemplateResponse(
        request=request, 
        name="dashboard.html"
    )
# ------------------------------

app.include_router(orders.router)
app.include_router(telemetry.router)

@app.middleware("http")
async def add_telemetry_middleware(request: Request, call_next):
    # [YOUR EXISTING MIDDLEWARE CODE REMAINS EXACTLY THE SAME]
    start_time = time.time()
    response = await call_next(request)
    process_time_ms = (time.time() - start_time) * 1000
    
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

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "CafeSync Core"}