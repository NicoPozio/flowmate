from pydantic import BaseModel, Field
from datetime import datetime

class ActivityBase(BaseModel):
    hobby_id: int
    duration_minutes: int = Field(..., gt=0)
    completion_timestamp: datetime = Field(default_factory=datetime.utcnow)

class ActivityCreate(ActivityBase):
    pass

class ActivityResponse(ActivityBase):
    activity_id: str
    user_id: str