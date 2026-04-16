from __future__ import annotations

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


class GestionCreateRequest(BaseModel):
    empresa: str = ""
    nombre_afiliado: str = ""
    tipo_gestion: str
    estado: str
    fecha_gestion: str
    observacion: str = ""
    origen: str = "manual"
    assigned_to_user_id: int | None = None

