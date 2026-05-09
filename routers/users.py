# routers/users.py
"""Admin-only user management.

Safeguards baked into every mutation:
  - You can't change or delete yourself (prevents accidental self-lockout).
  - You can't demote or delete the last remaining admin (prevents total
    lockout of the system).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

import models
import schemas
from database import get_db
from auth_utils import require_admin
from roles import Role

router = APIRouter(
    prefix="/users",
    tags=["User Management"],
    dependencies=[Depends(require_admin)],
)


def _count_admins(db: Session) -> int:
    return db.query(models.User).filter(models.User.role == Role.ADMIN).count()


@router.get("/", response_model=List[schemas.UserResponse])
def list_users(db: Session = Depends(get_db)):
    """List all users, newest first."""
    return db.query(models.User).order_by(models.User.created_at.desc()).all()


@router.put("/{user_id}/role", response_model=schemas.UserResponse)
def update_user_role(
    user_id: int,
    payload: schemas.RoleUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """Change a user's role. Admin only."""
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if target.id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="You cannot change your own role.",
        )

    # If we're demoting an admin, make sure at least one other admin remains.
    if target.role == Role.ADMIN and payload.role != Role.ADMIN:
        if _count_admins(db) <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot demote the last remaining admin.",
            )

    target.role = payload.role
    db.commit()
    db.refresh(target)
    return target


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """Delete a user. Admin only."""
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if target.id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="You cannot delete your own account.",
        )

    if target.role == Role.ADMIN and _count_admins(db) <= 1:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete the last remaining admin.",
        )

    db.delete(target)
    db.commit()
    return None
