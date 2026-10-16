from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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
    client_operation_id: str = ""


class GestionImportAmbiguousDebtor(BaseModel):
    rut: str
    nombre: str = ""
    companies: list[str] = Field(default_factory=list)


class GestionImportPreviewResponse(BaseModel):
    source_file: str
    file_sha256: str
    total_rows: int
    valid_rows: int
    new_rows: int
    duplicate_rows: int
    missing_debtors: int
    missing_ruts: list[str] = Field(default_factory=list)
    ambiguous_debtors: list[GestionImportAmbiguousDebtor] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class GestionImportResponse(BaseModel):
    source_file: str
    insertados: int
    omitidos_duplicados: int
    omitidos_sin_deudor: int
    deudores_actualizados: int
    advertencias: list[str] = Field(default_factory=list)

