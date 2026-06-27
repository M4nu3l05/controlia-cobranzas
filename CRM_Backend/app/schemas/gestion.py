from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class GestionItem(BaseModel):
    id: int
    empresa: str
    rut_afiliado: str
    nombre_afiliado: str
    tipo_gestion: str
    estado: str
    fecha_gestion: str
    observacion: str
    origen: str
    assigned_to_user_id: int | None = None
    derivation_created_by_user_id: int | None = None
    derivation_due_at: datetime | None = None
    derivation_completed_at: datetime | None = None
    derivation_is_overdue: bool = False


class GestionCreateRequest(BaseModel):
    empresa: str = ""
    nombre_afiliado: str = ""
    tipo_gestion: str
    estado: str
    fecha_gestion: str
    observacion: str = ""
    origen: str = "manual"
    assigned_to_user_id: int | None = None

