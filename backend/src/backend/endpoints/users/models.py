from pydantic import BaseModel, Field
from datetime import datetime
from decimal import Decimal

class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    weight_kg: Decimal = Field(..., gt=0, max_digits=5, decimal_places=2)
    daily_kcal_goal: int = Field(..., gt=0)

class UserCreate(UserBase):
    pass

class UserResponse(UserBase):
    user_id: str
    registration_date: datetime