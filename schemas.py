# schemas.py
from pydantic import BaseModel, ConfigDict, field_validator
from datetime import datetime


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

    # FIX: Reject zero or negative quantities at the schema level before they
    # reach the database.
    @field_validator("quantity")
    @classmethod
    def quantity_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("quantity must be a positive integer")
        return v


class OrderCreate(OrderBase):
    """Payload expected from the client to create an order."""
    pass


class OrderResponse(OrderBase):
    """Payload serialized and sent back to the client."""
    id: int
    is_completed: bool
    created_at: datetime

    # Instructs Pydantic to read data from SQLAlchemy ORM objects
    model_config = ConfigDict(from_attributes=True)
