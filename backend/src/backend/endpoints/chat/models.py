from pydantic import BaseModel
from typing import List, Optional

class ChatRequest(BaseModel):
    message: str # Example: "What should I do today?"

class Option(BaseModel):
    action: str
    label: str

class ChatResponse(BaseModel):
    message_id: str
    sender: str = "assistant"
    text: str
    suggestion_id: Optional[str] = None
    options: List[Option] = []