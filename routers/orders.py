# routers/orders.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload
from typing import List

import models
import schemas
from database import get_db
from auth_utils import get_current_user, require_fulfillment
from roles import Role, DASHBOARD_ROLES, ORDER_FULFILLMENT_ROLES
from security import require_csrf

router = APIRouter(
    prefix="/orders",
    tags=["Cafe Orders"],
    dependencies=[Depends(require_csrf)],
)


@router.post("/", response_model=schemas.OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(
    order: schemas.OrderCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Create an order. Any authenticated user can place orders (admin,
    barista, user, viewer all allowed — though viewer's UI hides the button)."""
    db_order = models.Order(
        item_name=order.item_name,
        quantity=order.quantity,
        placed_by_user_id=current_user.id,
    )
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    return schemas.OrderResponse.from_order(db_order)


@router.get("/", response_model=List[schemas.OrderResponse])
def read_orders(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """List orders. Allowed: admin, barista, viewer.
    Forbidden: user (they don't need to see the queue, only place orders)."""
    if current_user.role not in DASHBOARD_ROLES and current_user.role != Role.BARISTA:
        raise HTTPException(status_code=403, detail="Dashboard access required")

    orders = (
        db.query(models.Order)
        .options(joinedload(models.Order.placed_by))
        .order_by(models.Order.id.desc())
        .offset(skip).limit(limit).all()
    )
    return [schemas.OrderResponse.from_order(o) for o in orders]


@router.put("/{order_id}/complete", response_model=schemas.OrderResponse)
def complete_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_fulfillment),
):
    """Mark an order complete. Only admin or barista (the "Serve" action).
    Viewers and users can't trigger this even if they craft a request."""
    db_order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not db_order:
        raise HTTPException(status_code=404, detail="Order not found")

    db_order.is_completed = True
    db.commit()
    db.refresh(db_order)
    return schemas.OrderResponse.from_order(db_order)
