from pydantic import BaseModel, Field
from datetime import date

# 1. Modello per i dati in ENTRATA (quelli inviati da Android)
class BiometricLogCreate(BaseModel):
    steps_recorded: int = Field(..., ge=0)
    active_minutes: int = Field(default=0, ge=0)
    kcal_burned: int = Field(..., ge=0)

# 2. Modello per i dati in USCITA (quelli che FastAPI legge dal Database e manda ad Android)
class BiometricLogResponse(BaseModel):
    user_id: str
    record_date: date
    steps_recorded: int
    active_minutes: int
    kcal_burned: int