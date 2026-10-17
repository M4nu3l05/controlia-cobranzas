from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.deudor import DashboardSummaryResponse
from app.services.deudor_service import get_dashboard_summary_service
router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummaryResponse)
def dashboard_summary(
    empresas: str = Query(default=""),
    periodo_carga: str = Query(default=""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    empresas_list = [e.strip() for e in empresas.split(",") if e.strip()]
    executive_user_id = None
    if getattr(current_user, "role", "") == "ejecutivo":
        empresas_list = []
        executive_user_id = int(current_user.id)
    return get_dashboard_summary_service(
        db,
        empresas=empresas_list,
        periodo_carga=periodo_carga,
        executive_user_id=executive_user_id,
    )

