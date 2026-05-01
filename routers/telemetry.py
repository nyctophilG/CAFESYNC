# routers/telemetry.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List

import models
import schemas
from database import get_db

router = APIRouter(
    prefix="/telemetry",
    tags=["Technical Monitoring"]
)

@router.get("/logs", response_model=List[schemas.SystemLogResponse])
def get_recent_logs(limit: int = 50, db: Session = Depends(get_db)):
    """Retrieves the most recent system telemetry logs."""
    return db.query(models.SystemLog).order_by(models.SystemLog.timestamp.desc()).limit(limit).all()

@router.get("/metrics")
def get_system_metrics(db: Session = Depends(get_db)):
    """Aggregates core performance metrics for the Pod 2 Dashboard."""
    # Calculate average API latency
    avg_latency = db.query(func.avg(models.SystemLog.response_time_ms)).scalar() or 0.0
    
    # Count total requests
    total_requests = db.query(func.count(models.SystemLog.id)).scalar() or 0
    
    # Count 500 Internal Server Errors (like the one we just fixed)
    error_count = db.query(func.count(models.SystemLog.id)).filter(models.SystemLog.status_code >= 500).scalar() or 0

    return {
        "total_requests": total_requests,
        "average_latency_ms": round(avg_latency, 2),
        "error_count": error_count,
        "system_health": "Degraded" if error_count > 0 else "Optimal"
    }