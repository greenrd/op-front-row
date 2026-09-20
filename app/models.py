from datetime import datetime

from pydantic import BaseModel, Field


class Message(BaseModel):
    id: str
    thread_id: str
    text: str
    created_time: datetime
    sender_id: str
    sender_username: str
    from_me: bool = False


class Thread(BaseModel):
    id: str
    updated_time: datetime
    participant_id: str
    participant_username: str
    messages: list[Message]


class SummariseRequest(BaseModel):
    message_ids: list[str]


class SummaryItem(BaseModel):
    kind: str  # "question" | "suggestion"
    title: str
    summary: str
    count: int = 1
    message_ids: list[str] = Field(default_factory=list)


class SummaryResponse(BaseModel):
    items: list[SummaryItem]
    overview: str = ""
    messages_considered: int
    model: str
