from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.authorization import (
    AuthorizationError,
    can_operate_company,
    can_operate_debtor,
    is_privileged_operator,
    require_debtor_operation,
)
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
from app.services.user_service import get_current_user_carteras_service
from app.services.debtor_assignment_service import user_has_debtor_assignments

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
    offset: int = Query(default=0, ge=0),
    include_contact: bool = Query(default=False),
    assigned_user_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    empresas_permitidas: list[str] | None = None
    assignment_filter = assigned_user_id if is_privileged_operator(current_user) else None
    if not is_privileged_operator(current_user):
        if assigned_user_id is not None and int(assigned_user_id) != int(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para consultar los casos de otra ejecutiva.",
            )
        if empresa and not can_operate_company(db, current_user, empresa):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para consultar esta cartera.",
            )
        empresas_permitidas = get_current_user_carteras_service(
            db=db,
            executor=current_user,
        )
        if user_has_debtor_assignments(db, int(current_user.id)):
            assignment_filter = int(current_user.id)
    return list_deudores_service(
        db,
        q=q,
        empresa=empresa,
        periodo_carga=periodo_carga,
        limit=limit,
        offset=offset,
        include_contact=include_contact,
        empresas_permitidas=empresas_permitidas,
        assigned_user_id=assignment_filter,
    )


@router.get("/destinatarios", response_model=list[DestinatarioItem])
def list_destinatarios(
    empresa: str = Query(default=""),
    periodo_carga: str = Query(default=""),
    limit: int = Query(default=5000, ge=1, le=50000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Consultar la ficha de un deudor de otra cartera esta permitido, pero
    # extraer el padron masivo de correos queda acotado a las carteras propias.
    empresas_permitidas: list[str] | None = None
    assigned_user_id: int | None = None
    if not is_privileged_operator(current_user):
        if empresa and not can_operate_company(db, current_user, empresa):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para descargar los destinatarios de esta cartera.",
            )
        empresas_permitidas = get_current_user_carteras_service(
            db=db,
            executor=current_user,
        )
        if user_has_debtor_assignments(db, int(current_user.id)):
            assigned_user_id = int(current_user.id)

    return list_destinatarios_service(
        db,
        empresa=empresa,
        periodo_carga=periodo_carga,
        limit=limit,
        empresas_permitidas=empresas_permitidas,
        assigned_user_id=assigned_user_id,
    )


@router.get("/{rut}", response_model=DeudorDetalleResponse)
def get_deudor_detalle(
    rut: str,
    empresa: str = Query(default=""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        if not is_privileged_operator(current_user) and not can_operate_debtor(
            db, current_user, empresa, rut
        ):
            raise AuthorizationError("Este deudor está asignado a otra ejecutiva.")
        return get_deudor_detalle_service(
            db,
            rut=rut,
            empresa=empresa,
        )
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
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
        require_debtor_operation(db, current_user, payload.empresa, rut)
        return registrar_pago_service(
            db,
            executor=current_user,
            rut=rut,
            empresa=payload.empresa,
            expediente=payload.expediente,
            tipo_pago=payload.tipo_pago,
            monto=payload.monto,
            observaciones=payload.observaciones,
            nombre_afiliado=payload.nombre_afiliado,
            detalle_id=payload.detalle_id,
            fecha_efectiva=payload.fecha_efectiva,
            idempotency_key=payload.idempotency_key,
            distribucion=payload.distribucion,
            comprobante_nombre=payload.comprobante_nombre,
            comprobante_tipo=payload.comprobante_tipo,
            comprobante_base64=payload.comprobante_base64,
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


@router.put("/{rut}/cliente", response_model=ActualizarClienteResponse)
def update_deudor_cliente(
    rut: str,
    payload: ActualizarClienteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        require_debtor_operation(db, current_user, payload.empresa, rut)
        return update_deudor_cliente_service(
            db,
            executor=current_user,
            rut=rut,
            empresa=payload.empresa,
            rut_nuevo=payload.rut,
            nombre=payload.nombre,
            correo=payload.correo,
            correo_excel=payload.correo_excel,
            telefono_fijo=payload.telefono_fijo,
            telefono_movil=payload.telefono_movil,
            direccion=payload.direccion,
            comuna=payload.comuna,
            ciudad=payload.ciudad,
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

