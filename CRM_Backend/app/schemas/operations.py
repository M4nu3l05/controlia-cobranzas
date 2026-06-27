from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CustomerChangeAuditItem(BaseModel):
    id: int
    empresa: str
    rut_original: str
    field_name: str
    old_value: str
    new_value: str
    changed_by_user_id: int
    changed_by_username: str
    changed_at: datetime


class NotificationItem(BaseModel):
    id: int
    notification_type: str
    title: str
    message: str
    empresa: str
    rut_afiliado: str
    related_entity_type: str
    related_entity_id: int | None = None
    is_read: bool
    created_at: datetime
    read_at: datetime | None = None


class ReplacementCreateRequest(BaseModel):
    empresa: str = Field(min_length=1, max_length=80)
    replacement_user_id: int
    starts_at: datetime
    ends_at: datetime
    reason: str = Field(default="", max_length=255)


class ReplacementItem(BaseModel):
    id: int
    empresa: str
    titular_user_id: int
    titular_username: str = ""
    replacement_user_id: int
    replacement_username: str = ""
    starts_at: datetime
    ends_at: datetime
    reason: str
    created_by_user_id: int
    is_active: bool
    created_at: datetime
    ended_at: datetime | None = None
