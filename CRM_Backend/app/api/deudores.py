from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.deudor import (
    ActualizarClienteRequest,
    ActualizarClienteResponse,
    DeudorDetalleResponse,
    DeudorListResponse,
    RegistrarPagoRequest,
    RegistrarPagoResponse,
)
from app.services.deudor_service import (
    clear_all_deudores_service,
    clear_empresa_deudores_service,
    delete_deudor_individual_service,
    get_deudor_detalle_service,
    list_destinatarios_service,
    list_deudores_service,
    registrar_pago_service,
    update_deudor_cliente_service,
)
from app.schemas.deudor import DestinatarioItem
from app.schemas.auth import MessageResponse

router = APIRouter(prefix="/deudores", tags=["deudores"])


def _ensure_admin_or_supervisor(current_user: User) -> None:
    if current_user.role not in {"admin", "supervisor"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para limpiar bases de deudores.",
        )


@router.get("", response_model=DeudorListResponse)
def list_deudores(
    q: str = Query(default=""),
    empresa: str = Query(default=""),
    periodo_carga: str = Query(default=""),
    limit: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_deudores_service(
        db,
        q=q,
        empresa=empresa,
        periodo_carga=periodo_carga,
        limit=limit,
    )


@router.get("/destinatarios", response_model=list[DestinatarioItem])
def list_destinatarios(
    empresa: str = Query(default=""),
    periodo_carga: str = Query(default=""),
    limit: int = Query(default=5000, ge=1, le=50000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_destinatarios_service(
        db,
        empresa=empresa,
        periodo_carga=periodo_carga,
        limit=limit,
    )


@router.get("/{rut}", response_model=DeudorDetalleResponse)
def get_deudor_detalle(
    rut: str,
    empresa: str = Query(default=""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return get_deudor_detalle_service(
            db,
            rut=rut,
            empresa=empresa,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post("/{rut}/pagos", response_model=RegistrarPagoResponse)
def registrar_pago(
    rut: str,
    payload: RegistrarPagoRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return registrar_pago_service(
            db,
            rut=rut,
            empresa=payload.empresa,
            expediente=payload.expediente,
            tipo_pago=payload.tipo_pago,
            monto=payload.monto,
            observaciones=payload.observaciones,
            nombre_afiliado=payload.nombre_afiliado,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.put("/{rut}/cliente", response_model=ActualizarClienteResponse)
def update_deudor_cliente(
    rut: str,
    payload: ActualizarClienteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return update_deudor_cliente_service(
            db,
            rut=rut,
            empresa=payload.empresa,
            rut_nuevo=payload.rut,
            nombre=payload.nombre,
            correo=payload.correo,
            correo_excel=payload.correo_excel,
            telefono_fijo=payload.telefono_fijo,
            telefono_movil=payload.telefono_movil,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.delete("/{rut}", response_model=MessageResponse)
def delete_deudor_individual(
    rut: str,
    empresa: str = Query(default=""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_admin_or_supervisor(current_user)
    try:
        changed = delete_deudor_individual_service(
            db,
            empresa=empresa,
            rut=rut,
        )
        if changed:
            return MessageResponse(message=f"Se eliminó el registro del deudor {rut} en {empresa}.")
        return MessageResponse(message=f"No existían registros para el deudor {rut} en {empresa}.")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.delete("", response_model=MessageResponse)
def clear_all_deudores(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_admin_or_supervisor(current_user)
    empresas = clear_all_deudores_service(db)
    msg = "Se eliminaron todas las cargas de deudores."
    if empresas:
        msg += f" Empresas afectadas: {', '.join(empresas)}."
    return MessageResponse(message=msg)


@router.delete("/empresa/{empresa}", response_model=MessageResponse)
def clear_empresa_deudores(
    empresa: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_admin_or_supervisor(current_user)
    try:
        changed = clear_empresa_deudores_service(db, empresa=empresa)
        if changed:
            return MessageResponse(message=f"Se eliminaron los registros de deudores para {empresa}.")
        return MessageResponse(message=f"No existían registros de deudores para {empresa}.")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

