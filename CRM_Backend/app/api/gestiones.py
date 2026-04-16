from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.gestion import GestionCreateRequest, GestionItem
from app.services.gestion_service import (
    clear_all_gestiones_service,
    create_gestion_service,
    delete_gestion_service,
    list_gestiones_asignadas_para_usuario_service,
    list_gestiones_global_service,
    list_gestiones_service,
    marcar_gestion_asignada_realizada_service,
)
from app.schemas.auth import MessageResponse

router = APIRouter(tags=["gestiones"])


def _ensure_admin_or_supervisor(current_user: User) -> None:
    if current_user.role not in {"admin", "supervisor"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para consultar gestiones globales.",
        )


@router.get("/gestiones", response_model=list[GestionItem])
def list_gestiones_global(
    empresa: str = Query(default=""),
    fecha_desde: str = Query(default=""),
    fecha_hasta: str = Query(default=""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_admin_or_supervisor(current_user)
    return list_gestiones_global_service(
        db,
        empresa=empresa,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )


@router.get("/deudores/{rut}/gestiones", response_model=list[GestionItem])
def list_gestiones(
    rut: str,
    empresa: str = Query(default=""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_gestiones_service(db, rut=rut, empresa=empresa)


@router.get("/gestiones/asignadas/me", response_model=list[GestionItem])
def list_gestiones_asignadas_me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_gestiones_asignadas_para_usuario_service(
        db,
        user_id=int(current_user.id),
    )


@router.post("/deudores/{rut}/gestiones", response_model=GestionItem)
def create_gestion(
    rut: str,
    payload: GestionCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return create_gestion_service(db, rut=rut, payload=payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.delete("/gestiones/{gestion_id}")
def delete_gestion(
    gestion_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        delete_gestion_service(db, gestion_id=gestion_id)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/gestiones/{gestion_id}/marcar-realizada", response_model=GestionItem)
def marcar_gestion_realizada(
    gestion_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return marcar_gestion_asignada_realizada_service(
            db,
            gestion_id=gestion_id,
            executor=current_user,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.delete("/gestiones", response_model=MessageResponse)
def clear_all_gestiones(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_admin_or_supervisor(current_user)
    clear_all_gestiones_service(db)
    return MessageResponse(message="Se eliminaron todas las gestiones del sistema.")

