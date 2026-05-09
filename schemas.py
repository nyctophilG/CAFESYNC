# schemas.py
from pydantic import BaseModel, ConfigDict, EmailStr, field_validator
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
    id: int
    is_completed: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- User schemas ---

class UserResponse(BaseModel):
    """Public representation of a user — never includes password hash or
    TOTP secret."""
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
    """Sent when the user finishes scanning the QR and enters their first
    code. We verify against the pending secret stored in their session."""
    code: str

    @field_validator("code")
    @classmethod
    def code_format(cls, v: str) -> str:
        cleaned = v.strip().replace(" ", "")
        if not cleaned.isdigit() or len(cleaned) != 6:
            raise ValueError("Code must be 6 digits.")
        return cleaned


class TOTPSetupResponse(BaseModel):
    """Response when the user begins setup — gives the client the QR PNG
    and the secret (in case they want to copy-paste instead of scanning)."""
    qr_data_uri: str
    secret: str


class BackupCodesResponse(BaseModel):
    """Plaintext backup codes shown to the user EXACTLY ONCE after TOTP
    setup. Server never returns these again."""
    codes: List[str]
