from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class DeudorListItem(BaseModel):
    empresa: str
    rut_afiliado: str
    dv: str
    rut_completo: str
    nombre_afiliado: str
    estado_deudor: str
    bn: str
    nro_expediente: str
    max_emision_ok: str
    min_emision_ok: str
    copago: float
    total_pagos: float
    saldo_actual: float
    source_file: str = ""
    periodo_carga: str = ""


class DeudorListResponse(BaseModel):
    items: list[DeudorListItem]
    total: int


class DestinatarioItem(BaseModel):
    empresa: str
    rut_afiliado: str
    nombre_afiliado: str
    mail_afiliado: str
    estado_deudor: str
    nro_expediente: str
    copago: float
    total_pagos: float
    saldo_actual: float
    source_file: str = ""
    periodo_carga: str = ""


class DeudorDetalleItem(BaseModel):
    id: int
    empresa: str
    rut_afiliado: str
    dv: str
    rut_completo: str
    nombre_afiliado: str
    nombre_afil: str = ""
    rut_afil: str = ""
    fecha_pago: str = ""
    mail_afiliado: str
    bn: str
    telefono_fijo_afiliado: str
    telefono_movil_afiliado: str
    nro_expediente: str
    fecha_emision: str
    copago: float
    total_pagos: float
    saldo_actual: float
    cart56_fecha_recep: str
    cart56_fecha_recep_isa: str
    cart56_dias_pagar: str
    cart56_mto_pagar: float
    mail_emp: str
    telefono_empleador: str
    estado_deudor: str
    source_file: str = ""
    periodo_carga: str = ""


class DeudorDetalleResponse(BaseModel):
    rut: str
    empresa: str = ""
    resumen: DeudorListItem | None = None
    detalle: list[DeudorDetalleItem] = Field(default_factory=list)


class ImportDeudoresResponse(BaseModel):
    empresa: str
    resumen_insertados: int
    detalle_insertados: int
    detalle_nuevos: int = 0
    detalle_actualizados: int = 0
    detalle_omitidos: int = 0
    source_file: str
    periodo_carga: str = ""
    detalle_birlados: int = 0
    import_batch_id: int | None = None


class BirladoPreviewItem(BaseModel):
    detalle_id: int
    rut_afiliado: str
    rut_completo: str = ""
    nombre_afiliado: str = ""
    nro_expediente: str = ""
    fecha_emision: str = ""
    saldo_actual: float = 0
    estado_actual: str = ""


class ImportDeudoresPreviewResponse(BaseModel):
    empresa: str
    source_file: str
    file_sha256: str
    periodo_carga: str = ""
    registros_archivo: int
    nuevos_estimados: int
    existentes_estimados: int
    birlados: list[BirladoPreviewItem] = Field(default_factory=list)


class PaymentAllocationRequest(BaseModel):
    detalle_id: int
    monto: int = Field(gt=0)


class RegistrarPagoRequest(BaseModel):
    empresa: str
    expediente: str
    tipo_pago: str
    monto: float
    observaciones: str = ""
    nombre_afiliado: str = ""
    detalle_id: int | None = None
    fecha_efectiva: date = Field(default_factory=date.today)
    idempotency_key: str = Field(min_length=8, max_length=64)
    distribucion: list[PaymentAllocationRequest] = Field(default_factory=list)
    comprobante_nombre: str = ""
    comprobante_tipo: str = ""
    comprobante_base64: str = ""


class RegistrarPagoResponse(BaseModel):
    ok: bool = True
    empresa: str
    rut: str
    expediente: str
    tipo_pago: str
    monto: float
    saldo_expediente: float
    saldo_resumen: float
    total_pagos_resumen: float
    estado_deudor: str
    transaction_id: str = ""
    idempotent_replay: bool = False


class ActualizarClienteRequest(BaseModel):
    empresa: str
    rut: str
    nombre: str
    correo: str = ""
    correo_excel: str = ""
    telefono_fijo: str = ""
    telefono_movil: str = ""


class ActualizarClienteResponse(BaseModel):
    ok: bool = True
    empresa: str
    rut_original: str
    rut_actualizado: str
    nombre_afiliado: str
    mail_afiliado: str
    bn: str
    telefono_fijo_afiliado: str
    telefono_movil_afiliado: str


class DashboardCompanyItem(BaseModel):
    empresa: str
    deudores: int
    copago: float
    total_pagos: float
    saldo_actual: float
    sin_gestion: int
    gestionados: int
    cobertura_pct: float
    status_label: str
    status_level: str
    freshness: str = ""


class DashboardSummaryResponse(BaseModel):
    periodo_carga: str = ""
    periodos_disponibles: list[str] = Field(default_factory=list)
    total_deudores: int
    copago_total: float
    total_pagos_total: float
    saldo_total: float
    sin_gestion_total: int
    gestionados_total: int
    cobertura_pct: float
    pagos_vs_copago_pct: float
    contactados_total: int
    gestiones_hoy: int
    gestiones_7d: int
    estado_counts: dict[str, int] = Field(default_factory=dict)
    tipos_hoy: dict[str, int] = Field(default_factory=dict)
    health_label: str
    focus_text: str
    companies: list[DashboardCompanyItem] = Field(default_factory=list)

