# main.py
import time
from routers import orders
from fastapi import FastAPI, Request
from routers import orders, telemetry # Updated import
from database import engine, Base, SessionLocal
from models import SystemLog
import models

# Automatically generate tables in SQL Server on startup
# (In production, use Alembic migrations instead)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="CafeSync Technical Monitoring API")

app.include_router(orders.router)
app.include_router(telemetry.router)

@app.middleware("http")
async def add_telemetry_middleware(request: Request, call_next):
    """
    Pod 2 Requirement: Intercepts requests, measures latency, 
    and writes telemetry data to the SQL Server database.
    """
    start_time = time.time()
    
    # Execute the actual endpoint
    response = await call_next(request)
    
    process_time_ms = (time.time() - start_time) * 1000
    
    # Log to database asynchronously-safe block
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