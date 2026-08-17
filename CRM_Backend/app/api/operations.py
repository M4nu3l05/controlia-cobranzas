from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.authorization import AuthorizationError
from app.db.session import get_db
from app.models.user import User
from app.models.payment import PaymentReceipt, PaymentTransaction
from app.schemas.commission import (
    CommissionRateBulkRequest,
    CommissionRateItem,
    CommissionResetRequest,
    CommissionSummaryItem,
)
from app.schemas.operations import (
    CustomerChangeAuditItem,
    NotificationItem,
    ReplacementCreateRequest,
    ReplacementItem,
)
from app.services.commission_service import (
    commission_summary_service,
    list_commission_rates_service,
    reset_commissions_service,
    save_commission_rates_service,
)
from app.services.operations_service import (
    create_replacement_service,
    end_replacement_service,
    list_customer_change_audit_service,
    list_notifications_service,
    list_replacements_service,
    mark_notification_read_service,
)

router = APIRouter(prefix="/operations", tags=["operations"])

_FILENAME_SAFE_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._- "
)


def _safe_header_filename(raw: str) -> str:
    """Sanea el nombre para Content-Disposition.

    El valor viene de la base de datos, por lo que cualquier caracter de control
    (en especial CR/LF) permitiria inyectar cabeceras HTTP en la respuesta.
    """
    base = os.path.basename(str(raw or ""))
    limpio = "".join(ch for ch in base if ch in _FILENAME_SAFE_CHARS).strip()
    return limpio[:120] or "comprobante"


@router.get("/payments/{transaction_public_id}/receipt")
def download_payment_receipt(
    transaction_public_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    transaction = db.query(PaymentTransaction).filter(
        PaymentTransaction.public_id == transaction_public_id.strip()
    ).first()
    if not transaction:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El pago no existe.")
    receipt = db.query(PaymentReceipt).filter(
        PaymentReceipt.transaction_id == int(transaction.id)
    ).first()
    if not receipt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El pago no tiene comprobante adjunto.")
    filename = _safe_header_filename(receipt.filename)
    return Response(
        content=receipt.content,
        media_type=receipt.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/notifications/me", response_model=list[NotificationItem])
def list_my_notifications(
    unread_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_notifications_service(db, user=current_user, unread_only=unread_only)


@router.post("/notifications/{notification_id}/read", response_model=NotificationItem)
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return mark_notification_read_service(db, user=current_user, notification_id=notification_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/customer-changes", response_model=list[CustomerChangeAuditItem])
def list_customer_changes(
    empresa: str = Query(default=""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return list_customer_change_audit_service(db, executor=current_user, empresa=empresa)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("/replacements", response_model=list[ReplacementItem])
def list_replacements(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return list_replacements_service(db, executor=current_user)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/replacements", response_model=ReplacementItem, status_code=status.HTTP_201_CREATED)
def create_replacement(
    payload: ReplacementCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return create_replacement_service(db, executor=current_user, payload=payload)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/replacements/{replacement_id}/end", response_model=ReplacementItem)
def end_replacement(
    replacement_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return end_replacement_service(db, executor=current_user, replacement_id=replacement_id)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/comisiones/tasas", response_model=list[CommissionRateItem])
def list_commission_rates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return list_commission_rates_service(db, executor=current_user)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.put("/comisiones/tasas", response_model=list[CommissionRateItem])
def save_commission_rates(
    payload: CommissionRateBulkRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        normalized = [{"empresa": item.empresa, "percent": item.percent} for item in payload.rates]
        return save_commission_rates_service(db, executor=current_user, rates=normalized)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("/comisiones/resumen", response_model=list[CommissionSummaryItem])
def commission_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return commission_summary_service(db, executor=current_user)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/comisiones/reset", response_model=list[CommissionSummaryItem])
def reset_commissions(
    payload: CommissionResetRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return reset_commissions_service(
            db,
            executor=current_user,
            user_id=payload.user_id,
            note=payload.note,
        )
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
