from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.debtor_assignment import DebtorUserAssignment

ROLE_ADMIN = "admin"
ROLE_SUPERVISOR = "supervisor"
ROLE_EJECUTIVO = "ejecutivo"


class AuthorizationError(ValueError):
    """Regla de negocio rechazada por permisos del usuario."""


def _normalize_company(value: str) -> str:
    return str(value or "").strip()


def _company_key(value: str) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _rut_key(value: str) -> str:
    text_value = str(value or "").strip().replace(".", "").upper()
    if "-" in text_value:
        text_value = text_value.rsplit("-", 1)[0]
    return "".join(char for char in text_value if char.isdigit()).lstrip("0")


def _has_debtor_assignments_table(db: Session) -> bool:
    bind = db.get_bind()
    return bool(bind is not None and inspect(bind).has_table("debtor_user_assignments"))


def is_privileged_operator(user: User) -> bool:
    return str(user.role or "").strip().lower() in {ROLE_ADMIN, ROLE_SUPERVISOR}


def assigned_user_id_for_company(db: Session, company: str) -> int | None:
    company_txt = _normalize_company(company)
    if not company_txt:
        return None

    rows = db.execute(
        text(
            """
            SELECT empresa, user_id
            FROM cartera_asignaciones
            """
        ),
    ).all()
    company_key = _company_key(company_txt)
    for row in rows:
        if _company_key(row[0]) == company_key and row[1] is not None:
            return int(row[1])
    return None


def assigned_user_id_for_debtor(db: Session, company: str, rut: str) -> int | None:
    company_txt = _normalize_company(company)
    rut_txt = _rut_key(rut)
    if not company_txt or not rut_txt or not _has_debtor_assignments_table(db):
        return None
    row = db.query(DebtorUserAssignment).filter(
        DebtorUserAssignment.empresa == company_txt,
        DebtorUserAssignment.rut_afiliado == rut_txt,
    ).first()
    return int(row.user_id) if row is not None else None


def assigned_company_name(db: Session, company: str) -> str | None:
    company_txt = _normalize_company(company)
    if not company_txt:
        return None
    rows = db.execute(text("SELECT empresa FROM cartera_asignaciones")).all()
    company_key = _company_key(company_txt)
    for row in rows:
        empresa = _normalize_company(row[0])
        if _company_key(empresa) == company_key:
            return empresa
    return None


def can_operate_company(db: Session, user: User, company: str) -> bool:
    if is_privileged_operator(user):
        return True
    if str(user.role or "").strip().lower() != ROLE_EJECUTIVO:
        return False

    has_individual_assignment = None
    if _has_debtor_assignments_table(db):
        has_individual_assignment = db.query(DebtorUserAssignment.id).filter(
            DebtorUserAssignment.empresa == _normalize_company(company),
            DebtorUserAssignment.user_id == int(user.id),
        ).first()
    if has_individual_assignment is not None:
        return True

    assigned_user_id = assigned_user_id_for_company(db, company)
    if assigned_user_id is not None and assigned_user_id == int(user.id):
        return True

    replacement = db.execute(
        text(
            """
            SELECT id
            FROM cartera_temporary_replacements
            WHERE LOWER(TRIM(empresa)) = LOWER(:empresa)
              AND replacement_user_id = :user_id
              AND is_active = TRUE
              AND starts_at <= CURRENT_TIMESTAMP
              AND ends_at >= CURRENT_TIMESTAMP
            ORDER BY ends_at DESC
            LIMIT 1
            """
        ),
        {"empresa": assigned_company_name(db, company) or _normalize_company(company), "user_id": int(user.id)},
    ).first()
    return replacement is not None


def require_company_operation(db: Session, user: User, company: str) -> None:
    company_txt = _normalize_company(company)
    if not company_txt:
        raise AuthorizationError("Debes indicar una cartera valida.")
    if not can_operate_company(db, user, company_txt):
        raise AuthorizationError(
            "No tienes permiso para operar esta cartera. Puedes consultar, actualizar datos de contacto o derivar el caso."
        )


def can_operate_debtor(db: Session, user: User, company: str, rut: str) -> bool:
    if is_privileged_operator(user):
        return True
    if str(user.role or "").strip().lower() != ROLE_EJECUTIVO:
        return False
    owner_user_id = assigned_user_id_for_debtor(db, company, rut)
    if owner_user_id is None:
        return can_operate_company(db, user, company)
    if owner_user_id == int(user.id):
        return True
    replacement = db.execute(
        text("""
            SELECT id
            FROM cartera_temporary_replacements
            WHERE LOWER(TRIM(empresa)) = LOWER(:empresa)
              AND titular_user_id = :owner_user_id
              AND replacement_user_id = :user_id
              AND is_active = TRUE
              AND starts_at <= CURRENT_TIMESTAMP
              AND ends_at >= CURRENT_TIMESTAMP
            LIMIT 1
        """),
        {
            "empresa": _normalize_company(company),
            "owner_user_id": int(owner_user_id),
            "user_id": int(user.id),
        },
    ).first()
    return replacement is not None


def require_debtor_operation(db: Session, user: User, company: str, rut: str) -> None:
    if not can_operate_debtor(db, user, company, rut):
        raise AuthorizationError(
            "No tienes permiso para operar este deudor porque está asignado a otra ejecutiva."
        )


def require_supervisor(user: User, *, action: str) -> None:
    if str(user.role or "").strip().lower() != ROLE_SUPERVISOR:
        raise AuthorizationError(f"Solo un supervisor puede {action}.")


def resolve_derivation_target(
    db: Session,
    *,
    company: str,
    requested_user_id: int | None,
    rut: str = "",
) -> int:
    assigned_user_id = assigned_user_id_for_debtor(db, company, rut)
    if assigned_user_id is None:
        assigned_user_id = assigned_user_id_for_company(db, company)
    if assigned_user_id is None:
        raise AuthorizationError("La cartera no tiene una ejecutiva asignada para recibir la derivacion.")
    if requested_user_id is not None and int(requested_user_id) != assigned_user_id:
        raise AuthorizationError("La derivacion debe enviarse a la ejecutiva responsable de la cartera.")
    return assigned_user_id


def is_derivation(*, status: str, assigned_to_user_id: int | None) -> bool:
    normalized_status = " ".join(str(status or "").strip().lower().split())
    return assigned_to_user_id is not None or normalized_status in {
        "gestion asignada",
        "gestión asignada",
    }
