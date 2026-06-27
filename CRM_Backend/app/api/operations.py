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
from app.schemas.operations import (
    CustomerChangeAuditItem,
    NotificationItem,
    ReplacementCreateRequest,
    ReplacementItem,
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
    filename = os.path.basename(receipt.filename).replace('"', "") or "comprobante"
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
