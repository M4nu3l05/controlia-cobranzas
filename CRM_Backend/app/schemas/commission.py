from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CommissionRateItem(BaseModel):
    empresa: str
    percent: float
    updated_at: datetime | None = None
    updated_by_username: str = ""


class CommissionRateInput(BaseModel):
    empresa: str = Field(min_length=1, max_length=80)
    percent: float = Field(ge=0, le=100)


class CommissionRateBulkRequest(BaseModel):
    rates: list[CommissionRateInput] = Field(default_factory=list)


class CommissionCompanyBreakdown(BaseModel):
    empresa: str
    percent: float
    pagos: int
    monto_pagado_clp: int
    comision_clp: int


class CommissionSummaryItem(BaseModel):
    user_id: int
    username: str
    email: str = ""
    pagos: int = 0
    monto_pagado_clp: int = 0
    comision_clp: int = 0
    desde: datetime | None = None
    detalle: list[CommissionCompanyBreakdown] = Field(default_factory=list)


class CommissionResetRequest(BaseModel):
    user_id: int | None = None
    note: str = Field(default="", max_length=255)
