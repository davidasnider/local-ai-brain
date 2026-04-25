from typing import Optional

from pydantic import BaseModel, ConfigDict


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: Optional[str] = None
    input: str
    voice: str
    response_format: Optional[str] = "mp3"
    speed: Optional[float] = 1.0

    # Custom parameters for dynamic Kokoro voice routing
    character: Optional[str] = None
    season: Optional[str] = None


class TranscriptionResponse(BaseModel):
    text: str
