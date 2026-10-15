from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.authorization import AuthorizationError, require_debtor_operation
from app.db.session import get_db
from app.models.user import User
from app.schemas.gestion import (
    GestionCreateRequest,
    GestionImportPreviewResponse,
    GestionImportResponse,
    GestionItem,
)
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
from app.services.gestion_import_service import (
    import_gestiones_excel_service,
    preview_gestiones_import_service,
)

router = APIRouter(tags=["gestiones"])


def _ensure_admin_or_supervisor(current_user: User) -> None:
    if current_user.role not in {"admin", "supervisor"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para consultar gestiones globales.",
        )


def _parse_company_overrides(raw: str) -> dict[str, str]:
    if not str(raw or "").strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("La selección de carteras recibida no es válida.") from exc
    if not isinstance(payload, dict):
        raise ValueError("La selección de carteras recibida no es válida.")
    return {str(rut): str(company) for rut, company in payload.items()}


@router.post("/gestiones/import/preview", response_model=GestionImportPreviewResponse)
async def preview_gestiones_import(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_admin_or_supervisor(current_user)
    filename = file.filename or "gestiones.xlsx"
    if not filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Debes subir un archivo Excel válido.")
    try:
        result = preview_gestiones_import_service(
            db,
            content=await file.read(),
            source_file=filename,
        )
        return GestionImportPreviewResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"No se pudo generar la vista previa de gestiones: {exc}",
        ) from exc


@router.post("/gestiones/import", response_model=GestionImportResponse)
async def import_gestiones(
    expected_file_sha256: str = Form(...),
    company_overrides_json: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_admin_or_supervisor(current_user)
    filename = file.filename or "gestiones.xlsx"
    if not filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Debes subir un archivo Excel válido.")
    try:
        result = import_gestiones_excel_service(
            db,
            content=await file.read(),
            source_file=filename,
            expected_file_sha256=expected_file_sha256,
            company_overrides=_parse_company_overrides(company_overrides_json),
        )
        return GestionImportResponse(**result)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"No se pudo importar la base de gestiones: {exc}",
        ) from exc


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
    try:
        require_debtor_operation(db, current_user, empresa, rut)
        return list_gestiones_service(db, rut=rut, empresa=empresa)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


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
        return create_gestion_service(
            db,
            rut=rut,
            payload=payload,
            executor=current_user,
        )
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
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
        delete_gestion_service(
            db,
            gestion_id=gestion_id,
            executor=current_user,
        )
        return {"ok": True}
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
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
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
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

