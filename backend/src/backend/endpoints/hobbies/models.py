from pydantic import BaseModel, Field
from decimal import Decimal

class HobbyResponse(BaseModel):
    hobby_id: int
    hobby_name: str
    met_value: Decimal

class UserHobbyBase(BaseModel):
    hobby_id: int
    preference_level: int = Field(..., ge=1, le=5)

class UserHobbyCreate(UserHobbyBase):
    pass

class UserHobbyResponse(UserHobbyBase):
    user_id: str