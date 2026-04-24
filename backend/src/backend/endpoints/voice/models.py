from pydantic import BaseModel

class VoiceRequest(BaseModel):
    message: str 

class VoiceResponse(BaseModel):
    text: str