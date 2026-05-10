# schemas.py
from pydantic import BaseModel, ConfigDict, field_validator
from datetime import datetime
from typing import Optional, List
from roles import ALL_ROLES


class SystemLogResponse(BaseModel):
    id: int
    endpoint: str
    method: str
    status_code: int
    response_time_ms: float
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)


class OrderBase(BaseModel):
    item_name: str
    quantity: int

    @field_validator("quantity")
    @classmethod
    def quantity_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("quantity must be a positive integer")
        return v


class OrderCreate(OrderBase):
    pass


class OrderResponse(OrderBase):
    """Includes placed_by_username so the admin queue can show who ordered
    what. Field is optional since old rows have NULL placer."""
    id: int
    is_completed: bool
    created_at: datetime
    placed_by_username: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_order(cls, order):
        """Helper since SQLAlchemy doesn't auto-fill placed_by_username."""
        return cls(
            id=order.id,
            item_name=order.item_name,
            quantity=order.quantity,
            is_completed=order.is_completed,
            created_at=order.created_at,
            placed_by_username=order.placed_by.username if order.placed_by else None,
        )


# --- User schemas ---

class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    created_at: datetime
    email: Optional[str] = None
    totp_enabled: bool = False

    model_config = ConfigDict(from_attributes=True)


class RoleUpdate(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v: str) -> str:
        if v not in ALL_ROLES:
            raise ValueError(
                f"Invalid role '{v}'. Must be one of: {sorted(ALL_ROLES)}"
            )
        return v


# --- 2FA schemas ---

class TOTPConfirmRequest(BaseModel):
    code: str

    @field_validator("code")
    @classmethod
    def code_format(cls, v: str) -> str:
        cleaned = v.strip().replace(" ", "")
        if not cleaned.isdigit() or len(cleaned) != 6:
            raise ValueError("Code must be 6 digits.")
        return cleaned


class TOTPSetupResponse(BaseModel):
    qr_data_uri: str
    secret: str


class BackupCodesResponse(BaseModel):
    codes: List[str]
