from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationError, assigned_user_id_for_company
from app.models.operations import (
    CarteraTemporaryReplacement,
    CustomerChangeAudit,
    UserNotification,
)
from app.models.user import User
from app.schemas.operations import (
    CustomerChangeAuditItem,
    NotificationItem,
    ReplacementCreateRequest,
    ReplacementItem,
)


def create_notification(
    db: Session,
    *,
    user_id: int,
    notification_type: str,
    title: str,
    message: str,
    empresa: str = "",
    rut_afiliado: str = "",
    related_entity_type: str = "",
    related_entity_id: int | None = None,
) -> UserNotification:
    row = UserNotification(
        user_id=int(user_id),
        notification_type=str(notification_type or "").strip(),
        title=str(title or "").strip(),
        message=str(message or "").strip(),
        empresa=str(empresa or "").strip(),
        rut_afiliado=str(rut_afiliado or "").strip(),
        related_entity_type=str(related_entity_type or "").strip(),
        related_entity_id=related_entity_id,
        is_read=False,
    )
    db.add(row)
    return row


def list_notifications_service(
    db: Session,
    *,
    user: User,
    unread_only: bool = False,
    limit: int = 100,
) -> list[NotificationItem]:
    query = db.query(UserNotification).filter(UserNotification.user_id == int(user.id))
    if unread_only:
        query = query.filter(UserNotification.is_read.is_(False))
    rows = query.order_by(UserNotification.created_at.desc(), UserNotification.id.desc()).limit(limit).all()
    return [NotificationItem.model_validate(row, from_attributes=True) for row in rows]


def mark_notification_read_service(db: Session, *, user: User, notification_id: int) -> NotificationItem:
    row = db.query(UserNotification).filter(
        UserNotification.id == int(notification_id),
        UserNotification.user_id == int(user.id),
    ).first()
    if not row:
        raise ValueError("La notificacion indicada no existe.")
    row.is_read = True
    row.read_at = datetime.now()
    db.add(row)
    db.commit()
    db.refresh(row)
    return NotificationItem.model_validate(row, from_attributes=True)


def list_customer_change_audit_service(
    db: Session,
    *,
    executor: User,
    empresa: str = "",
    limit: int = 5000,
) -> list[CustomerChangeAuditItem]:
    if str(executor.role or "").strip().lower() not in {"admin", "supervisor"}:
        raise AuthorizationError("No tienes permiso para consultar la auditoria de clientes.")
    query = db.query(CustomerChangeAudit)
    empresa_txt = str(empresa or "").strip()
    if empresa_txt:
        query = query.filter(CustomerChangeAudit.empresa == empresa_txt)
    rows = query.order_by(CustomerChangeAudit.changed_at.desc(), CustomerChangeAudit.id.desc()).limit(limit).all()
    return [CustomerChangeAuditItem.model_validate(row, from_attributes=True) for row in rows]


def _replacement_item(db: Session, row: CarteraTemporaryReplacement) -> ReplacementItem:
    titular = db.query(User).filter(User.id == row.titular_user_id).first()
    replacement = db.query(User).filter(User.id == row.replacement_user_id).first()
    now = datetime.now()
    effectively_active = bool(row.is_active and row.starts_at <= now <= row.ends_at)
    return ReplacementItem(
        id=int(row.id),
        empresa=row.empresa,
        titular_user_id=int(row.titular_user_id),
        titular_username=str(getattr(titular, "username", "") or ""),
        replacement_user_id=int(row.replacement_user_id),
        replacement_username=str(getattr(replacement, "username", "") or ""),
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        reason=row.reason,
        created_by_user_id=int(row.created_by_user_id),
        is_active=effectively_active,
        created_at=row.created_at,
        ended_at=row.ended_at,
    )


def create_replacement_service(
    db: Session,
    *,
    executor: User,
    payload: ReplacementCreateRequest,
) -> ReplacementItem:
    if str(executor.role or "").strip().lower() not in {"admin", "supervisor"}:
        raise AuthorizationError("No tienes permiso para crear reemplazos temporales.")
    if payload.ends_at <= payload.starts_at:
        raise ValueError("La fecha de termino debe ser posterior a la fecha de inicio.")

    titular_user_id = assigned_user_id_for_company(db, payload.empresa)
    if titular_user_id is None:
        raise ValueError("La cartera no tiene una ejecutiva titular asignada.")
    if int(titular_user_id) == int(payload.replacement_user_id):
        raise ValueError("La reemplazante debe ser distinta de la ejecutiva titular.")

    replacement = db.query(User).filter(User.id == int(payload.replacement_user_id)).first()
    if not replacement or replacement.role != "ejecutivo" or not bool(replacement.is_active):
        raise ValueError("La reemplazante debe ser una ejecutiva activa.")

    overlap = db.query(CarteraTemporaryReplacement).filter(
        CarteraTemporaryReplacement.empresa == payload.empresa.strip(),
        CarteraTemporaryReplacement.is_active.is_(True),
        CarteraTemporaryReplacement.starts_at < payload.ends_at,
        CarteraTemporaryReplacement.ends_at > payload.starts_at,
    ).first()
    if overlap:
        raise ValueError("Ya existe un reemplazo activo que se cruza con ese periodo.")

    row = CarteraTemporaryReplacement(
        empresa=payload.empresa.strip(),
        titular_user_id=int(titular_user_id),
        replacement_user_id=int(replacement.id),
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        reason=payload.reason.strip(),
        created_by_user_id=int(executor.id),
        is_active=True,
    )
    db.add(row)
    db.flush()
    create_notification(
        db,
        user_id=int(replacement.id),
        notification_type="temporary_replacement",
        title="Reemplazo temporal asignado",
        message=f"Puedes operar la cartera {row.empresa} entre {row.starts_at} y {row.ends_at}.",
        empresa=row.empresa,
        related_entity_type="replacement",
        related_entity_id=int(row.id),
    )
    db.commit()
    db.refresh(row)
    return _replacement_item(db, row)


def list_replacements_service(db: Session, *, executor: User) -> list[ReplacementItem]:
    if str(executor.role or "").strip().lower() not in {"admin", "supervisor"}:
        raise AuthorizationError("No tienes permiso para consultar reemplazos temporales.")
    rows = db.query(CarteraTemporaryReplacement).order_by(
        CarteraTemporaryReplacement.is_active.desc(),
        CarteraTemporaryReplacement.starts_at.desc(),
    ).all()
    return [_replacement_item(db, row) for row in rows]


def end_replacement_service(
    db: Session,
    *,
    executor: User,
    replacement_id: int,
) -> ReplacementItem:
    if str(executor.role or "").strip().lower() not in {"admin", "supervisor"}:
        raise AuthorizationError("No tienes permiso para finalizar reemplazos temporales.")
    row = db.query(CarteraTemporaryReplacement).filter(
        CarteraTemporaryReplacement.id == int(replacement_id)
    ).first()
    if not row:
        raise ValueError("El reemplazo temporal no existe.")
    row.is_active = False
    row.ended_at = datetime.now()
    db.add(row)
    db.commit()
    db.refresh(row)
    return _replacement_item(db, row)
