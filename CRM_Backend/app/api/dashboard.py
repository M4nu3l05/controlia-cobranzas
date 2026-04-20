from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.deudor import DashboardSummaryResponse
from app.schemas.session_history import DashboardSessionsResponse
from app.services.deudor_service import get_dashboard_summary_service
from app.services.session_history_service import list_sessions_month, list_sessions_today
from app.services.user_service import get_current_user_carteras_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _ensure_admin_or_supervisor(current_user: User) -> None:
    if current_user.role not in {"admin", "supervisor"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para consultar este panel.",
        )


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


@router.get("/sessions", response_model=DashboardSessionsResponse)
def dashboard_sessions(
    role: str = Query(default="ejecutivo"),
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_admin_or_supervisor(current_user)

    if role not in {"admin", "supervisor", "ejecutivo"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rol inválido para historial de sesiones.",
        )

    now = datetime.now()
    y = int(year or now.year)
    m = int(month or now.month)

    if m < 1 or m > 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mes inválido.",
        )

    return DashboardSessionsResponse(
        today=list_sessions_today(db=db, role=role),
        month=list_sessions_month(db=db, year=y, month=m, role=role),
    )

