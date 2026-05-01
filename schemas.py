# schemas.py
from pydantic import BaseModel, ConfigDict
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