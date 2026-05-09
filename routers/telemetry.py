# routers/telemetry.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
import math

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
    """Aggregates core performance metrics, including P95 tail latency.
    
    Note: All metrics (avg, P95, error count) are computed over the same
    rolling window of the 1000 most recent requests for consistency.
    """
    # Use a consistent rolling window of the 1000 most recent logs for all metrics
    WINDOW = 1000

    recent_logs = db.query(models.SystemLog)\
                    .order_by(models.SystemLog.timestamp.desc())\
                    .limit(WINDOW)\
                    .all()

    total_requests = db.query(func.count(models.SystemLog.id)).scalar() or 0

    if not recent_logs:
        return {
            "total_requests": total_requests,
            "average_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "error_count": 0,
            "system_health": "Optimal"
        }

    latencies = sorted([log.response_time_ms for log in recent_logs])

    # Average latency over the window
    avg_latency = sum(latencies) / len(latencies)

    # FIX: Clamp P95 index to valid bounds to prevent off-by-one on small datasets
    p95_index = min(math.ceil(0.95 * len(latencies)) - 1, len(latencies) - 1)
    p95_latency = latencies[p95_index]

    # Error count over the same window
    error_count = sum(1 for log in recent_logs if log.status_code >= 500)

    return {
        "total_requests": total_requests,
        "average_latency_ms": round(avg_latency, 2),
        "p95_latency_ms": round(p95_latency, 2),
        "error_count": error_count,
        "system_health": "Degraded" if error_count > 0 else "Optimal"
    }
