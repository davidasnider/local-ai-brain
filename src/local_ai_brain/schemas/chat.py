from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict


class ChatMessage(BaseModel):
    role: str
    content: Union[str, List[Dict[str, Any]]]
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: Optional[str] = None
    messages: List[ChatMessage]
    temperature: Optional[float] = 1.0
    top_p: Optional[float] = 1.0
    n: Optional[int] = 1
    stream: Optional[bool] = False
    stop: Optional[Union[str, List[str]]] = None
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = 0.0
    frequency_penalty: Optional[float] = 0.0
    logit_bias: Optional[Dict[str, float]] = None
    user: Optional[str] = None
