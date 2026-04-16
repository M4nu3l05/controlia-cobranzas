from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.deudor import DashboardSummaryResponse
from app.services.deudor_service import get_dashboard_summary_service
from app.services.user_service import get_current_user_carteras_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummaryResponse)
def dashboard_summary(
    empresas: str = Query(default=""),
    periodo_carga: str = Query(default=""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    empresas_list = [e.strip() for e in empresas.split(",") if e.strip()]
    if getattr(current_user, "role", "") == "ejecutivo":
        empresas_list = get_current_user_carteras_service(
            db=db,
            executor=current_user,
        )
    return get_dashboard_summary_service(db, empresas=empresas_list, periodo_carga=periodo_carga)

