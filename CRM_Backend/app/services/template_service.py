from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.email_template import EmailTemplate
from app.schemas.template import (
    EmailTemplateCreateRequest,
    EmailTemplateItem,
    EmailTemplateUpdateRequest,
)

DEFAULT_EMAIL_TEMPLATES = [
    {
        "nombre": "Recordatorio de deuda",
        "asunto": "Recordatorio de saldo pendiente - {empresa}",
        "cuerpo": (
            "Estimado/a {nombre},\n\n"
            "Le contactamos para recordarle que registra un saldo pendiente de "
            "${saldo} en {empresa}.\n\n"
            "Le solicitamos regularizar su situacion a la brevedad. Si ya realizo "
            "el pago, por favor ignore este mensaje.\n\n"
            "Atentamente,\n"
            "Equipo de Controlia Cobranzas"
        ),
    },
    {
        "nombre": "Aviso de mora",
        "asunto": "Aviso de cuenta en mora - Expediente {nro_expediente}",
        "cuerpo": (
            "Estimado/a {nombre},\n\n"
            "Su cuenta con expediente N {nro_expediente} presenta un saldo "
            "vencido de ${saldo}.\n\n"
            "Para evitar mayores consecuencias, le invitamos a ponerse en "
            "contacto con nosotros para acordar un plan de pago.\n\n"
            "Atentamente,\n"
            "Equipo de Controlia Cobranzas"
        ),
    },
    {
        "nombre": "Primer contacto",
        "asunto": "Informacion sobre su cuenta - {empresa}",
        "cuerpo": (
            "Estimado/a {nombre},\n\n"
            "Nos comunicamos en representacion de {empresa} para informarle "
            "que hemos recibido su caso para gestion de cobranza.\n\n"
            "Monto copago: ${copago}\n"
            "Pagos registrados: ${total_pagos}\n"
            "Saldo pendiente: ${saldo}\n\n"
            "Para consultas, responda este correo o contactenos directamente.\n\n"
            "Atentamente,\n"
            "Equipo de Controlia Cobranzas"
        ),
    },
]


def _to_item(row: EmailTemplate) -> EmailTemplateItem:
    return EmailTemplateItem.model_validate(row)


def _norm_name(value: str) -> str:
    return str(value or "").strip()


def ensure_default_email_templates(db: Session) -> None:
    exists = db.query(EmailTemplate.id).first()
    if exists:
        return

    for tpl in DEFAULT_EMAIL_TEMPLATES:
        db.add(
            EmailTemplate(
                nombre=str(tpl.get("nombre", "")).strip(),
                asunto=str(tpl.get("asunto", "")).strip(),
                cuerpo=str(tpl.get("cuerpo", "")).strip(),
                is_active=True,
            )
        )
    db.commit()


def list_email_templates_service(db: Session) -> list[EmailTemplateItem]:
    rows = (
        db.query(EmailTemplate)
        .filter(EmailTemplate.is_active.is_(True))
        .order_by(func.lower(EmailTemplate.nombre).asc(), EmailTemplate.id.asc())
        .all()
    )
    return [_to_item(r) for r in rows]


def create_email_template_service(
    db: Session,
    *,
    payload: EmailTemplateCreateRequest,
) -> EmailTemplateItem:
    nombre = _norm_name(payload.nombre)
    if not nombre:
        raise ValueError("El nombre de la plantilla es obligatorio.")

    exists = (
        db.query(EmailTemplate)
        .filter(func.lower(EmailTemplate.nombre) == nombre.lower())
        .first()
    )
    if exists:
        raise ValueError("Ya existe una plantilla con ese nombre.")

    row = EmailTemplate(
        nombre=nombre,
        asunto=str(payload.asunto or "").strip(),
        cuerpo=str(payload.cuerpo or "").strip(),
        is_active=bool(payload.is_active),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_item(row)


def update_email_template_service(
    db: Session,
    *,
    template_id: int,
    payload: EmailTemplateUpdateRequest,
) -> EmailTemplateItem:
    row = db.query(EmailTemplate).filter(EmailTemplate.id == int(template_id)).first()
    if not row:
        raise ValueError("La plantilla indicada no existe.")

    if payload.nombre is not None:
        nombre = _norm_name(payload.nombre)
        if not nombre:
            raise ValueError("El nombre de la plantilla es obligatorio.")
        exists = (
            db.query(EmailTemplate)
            .filter(func.lower(EmailTemplate.nombre) == nombre.lower(), EmailTemplate.id != row.id)
            .first()
        )
        if exists:
            raise ValueError("Ya existe una plantilla con ese nombre.")
        row.nombre = nombre

    if payload.asunto is not None:
        row.asunto = str(payload.asunto).strip()
    if payload.cuerpo is not None:
        row.cuerpo = str(payload.cuerpo).strip()
    if payload.is_active is not None:
        row.is_active = bool(payload.is_active)

    db.commit()
    db.refresh(row)
    return _to_item(row)


def delete_email_template_service(db: Session, *, template_id: int) -> None:
    row = db.query(EmailTemplate).filter(EmailTemplate.id == int(template_id)).first()
    if not row:
        raise ValueError("La plantilla indicada no existe.")

    active_count = db.query(EmailTemplate).filter(EmailTemplate.is_active.is_(True)).count()
    if active_count <= 1 and row.is_active:
        raise ValueError("Debe existir al menos una plantilla activa.")

    db.delete(row)
    db.commit()
