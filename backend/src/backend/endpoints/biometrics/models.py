from pydantic import BaseModel, Field
from datetime import datetime

class BiometricLogBase(BaseModel):
    steps_recorded: int = Field(..., ge=0)
    kcal_burned: int = Field(..., ge=0)
    log_timestamp: datetime = Field(default_factory=datetime.utcnow)

class BiometricLogCreate(BiometricLogBase):
    pass

class BiometricLogResponse(BiometricLogBase):
    log_id: str
    user_id: str