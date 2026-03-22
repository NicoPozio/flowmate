from pydantic import BaseModel, Field
from datetime import time

class ScheduleBase(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6)
    start_time: time
    end_time: time
    event_type: str = Field(..., max_length=50)

class ScheduleCreate(ScheduleBase):
    pass

class ScheduleResponse(ScheduleBase):
    event_id: str
    user_id: str