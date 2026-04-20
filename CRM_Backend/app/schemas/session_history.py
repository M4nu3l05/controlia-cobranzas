from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SessionHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    email: str
    username: str
    role: str
    login_at: datetime
    logout_at: datetime | None = None


class DashboardSessionsResponse(BaseModel):
    today: list[SessionHistoryItem] = Field(default_factory=list)
    month: list[SessionHistoryItem] = Field(default_factory=list)


class LogoutRequest(BaseModel):
    session_history_id: int | None = None
