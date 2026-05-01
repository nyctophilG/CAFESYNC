# models.py
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from datetime import datetime
from database import Base

class SystemLog(Base):
    """Pod 2: Technical Monitoring Telemetry Table"""
    __tablename__ = "technical_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    endpoint = Column(String(255), nullable=False)
    method = Column(String(10), nullable=False)
    status_code = Column(Integer, nullable=False)
    response_time_ms = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

class Order(Base):
    """Pod 1: Cafe Business Logic Table"""
    __tablename__ = "cafe_orders"
    
    id = Column(Integer, primary_key=True, index=True)
    item_name = Column(String(100), nullable=False)
    quantity = Column(Integer, nullable=False)
    is_completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)