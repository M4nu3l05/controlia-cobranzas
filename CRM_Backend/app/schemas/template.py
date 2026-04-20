from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class EmailTemplateItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    asunto: str
    cuerpo: str
    is_active: bool = True


class EmailTemplateCreateRequest(BaseModel):
    nombre: str
    asunto: str = ""
    cuerpo: str = ""
    is_active: bool = True


class EmailTemplateUpdateRequest(BaseModel):
    nombre: str | None = None
    asunto: str | None = None
    cuerpo: str | None = None
    is_active: bool | None = None
