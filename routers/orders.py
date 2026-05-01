# routers/orders.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

import models
import schemas
from database import get_db

router = APIRouter(
    prefix="/orders",
    tags=["Cafe Orders"]
)

@router.post("/", response_model=schemas.OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(order: schemas.OrderCreate, db: Session = Depends(get_db)):
    """Creates a new cafe order."""
    db_order = models.Order(item_name=order.item_name, quantity=order.quantity)
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    return db_order

@router.get("/", response_model=List[schemas.OrderResponse])
def read_orders(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """Retrieves a paginated list of all orders."""
    # Added explicit ordering to satisfy MSSQL engine constraints
    orders = db.query(models.Order).order_by(models.Order.id.desc()).offset(skip).limit(limit).all()
    return orders

@router.put("/{order_id}/complete", response_model=schemas.OrderResponse)
def complete_order(order_id: int, db: Session = Depends(get_db)):
    """Marks an existing order as completed."""
    db_order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not db_order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    db_order.is_completed = True
    db.commit()
    db.refresh(db_order)
    return db_order