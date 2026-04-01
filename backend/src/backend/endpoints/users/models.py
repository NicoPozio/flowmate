from pydantic import BaseModel, Field
from datetime import datetime
from decimal import Decimal

# --- MODELLI UTENTE ---
class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    weight_kg: Decimal = Field(..., gt=0, max_digits=5, decimal_places=2)
    daily_kcal_goal: int = Field(..., gt=0)
    daily_steps_goal: int = Field(..., gt=0) # Aggiunto qui

class UserCreate(UserBase):
    pass

class UserResponse(UserBase):
    user_id: str
    registration_date: datetime
    has_hobbies: bool = False # <-- Indica se l'utente ha già scelto gli hobby

# --- MODELLI HEALTH CONNECT ---
class DailyHealthCreate(BaseModel):
    date: str  # Formato YYYY-MM-DD
    steps: int
    active_minutes: int
    calories_burned: int