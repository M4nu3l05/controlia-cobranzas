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
    return inspect(db.connection()).has_table("debtor_user_assignments")


def _has_table(db: Session, table_name: str) -> bool:
    return inspect(db.connection()).has_table(table_name)


def _table_columns(db: Session, table_name: str) -> set[str]:
    connection = db.connection()
    inspector = inspect(connection)
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name)}


def is_privileged_operator(user: User) -> bool:
    return str(user.role or "").strip().lower() in {ROLE_ADMIN, ROLE_SUPERVISOR}


def primary_user_id_for_company(db: Session, company: str) -> int | None:
    company_txt = _normalize_company(company)
    if not company_txt or not _has_table(db, "cartera_asignaciones"):
        return None

    columns = _table_columns(db, "cartera_asignaciones")
    primary_filter = "WHERE is_primary = TRUE" if "is_primary" in columns else ""
    rows = db.execute(text(
        f"SELECT empresa, user_id FROM cartera_asignaciones {primary_filter}"
    )).all()
    company_key = _company_key(company_txt)
    for row in rows:
        if _company_key(row[0]) == company_key and row[1] is not None:
            return int(row[1])
    return None


def assigned_user_id_for_company(db: Session, company: str) -> int | None:
    """Alias compatible: devuelve exclusivamente al supervisor titular."""
    return primary_user_id_for_company(db, company)


def assigned_user_id_for_debtor(db: Session, company: str, rut: str) -> int | None:
    company_txt = _normalize_company(company)
    rut_txt = _rut_key(rut)
    if not company_txt or not rut_txt or not _has_debtor_assignments_table(db):
        return None
    rows = db.query(DebtorUserAssignment).filter(
        DebtorUserAssignment.rut_afiliado == rut_txt,
    ).all()
    company_key = _company_key(company_txt)
    for row in rows:
        if _company_key(row.empresa) == company_key:
            return int(row.user_id)
    return None


def assigned_company_name(db: Session, company: str) -> str | None:
    company_txt = _normalize_company(company)
    if not company_txt or not _has_table(db, "cartera_asignaciones"):
        return None
    rows = db.execute(text("SELECT empresa FROM cartera_asignaciones")).all()
    company_key = _company_key(company_txt)
    for row in rows:
        empresa = _normalize_company(row[0])
        if _company_key(empresa) == company_key:
            return empresa
    return None


def executive_debtor_visibility_scope(
    db: Session,
    user_id: int,
) -> tuple[set[str], dict[str, set[int]]]:
    """Devuelve carteras completas y responsables individuales visibles.

    Una cartera con al menos una asignacion individual usa siempre ese reparto.
    La asignacion general de cartera solo actua como compatibilidad cuando la
    cartera no tiene distribucion individual.
    """
    target_user_id = int(user_id)
    distributed_names: dict[str, str] = {}
    owner_ids_by_key: dict[str, set[int]] = {}

    if _has_debtor_assignments_table(db):
        assignment_rows = db.query(
            DebtorUserAssignment.empresa,
            DebtorUserAssignment.user_id,
        ).distinct().all()
        for empresa, owner_user_id in assignment_rows:
            empresa_txt = _normalize_company(empresa)
            key = _company_key(empresa_txt)
            if not key:
                continue
            distributed_names.setdefault(key, empresa_txt)
            if int(owner_user_id) == target_user_id:
                owner_ids_by_key.setdefault(key, set()).add(target_user_id)

    full_companies_by_key: dict[str, str] = {}
    if _has_table(db, "cartera_asignaciones"):
        portfolio_rows = db.execute(
            text(
                """
                SELECT empresa
                FROM cartera_asignaciones
                WHERE user_id = :user_id
                """
            ),
            {"user_id": target_user_id},
        ).all()
        for (empresa,) in portfolio_rows:
            empresa_txt = _normalize_company(empresa)
            key = _company_key(empresa_txt)
            if key and key not in distributed_names:
                full_companies_by_key.setdefault(key, empresa_txt)

    replacement_columns = _table_columns(db, "cartera_temporary_replacements")
    if replacement_columns:
        includes_owner = "titular_user_id" in replacement_columns
        owner_select = "titular_user_id" if includes_owner else "NULL"
        replacement_rows = db.execute(
            text(
                f"""
                SELECT empresa, {owner_select} AS titular_user_id
                FROM cartera_temporary_replacements
                WHERE replacement_user_id = :user_id
                  AND is_active = TRUE
                  AND starts_at <= CURRENT_TIMESTAMP
                  AND ends_at >= CURRENT_TIMESTAMP
                """
            ),
            {"user_id": target_user_id},
        ).all()
        for empresa, owner_user_id in replacement_rows:
            empresa_txt = _normalize_company(empresa)
            key = _company_key(empresa_txt)
            if not key:
                continue
            if key not in distributed_names:
                full_companies_by_key.setdefault(key, empresa_txt)
            elif owner_user_id is not None:
                owner_ids_by_key.setdefault(key, set()).add(int(owner_user_id))

    owner_ids_by_company = {
        distributed_names[key]: owner_ids
        for key, owner_ids in owner_ids_by_key.items()
        if key in distributed_names and owner_ids
    }
    return set(full_companies_by_key.values()), owner_ids_by_company


def company_has_debtor_assignments(db: Session, company: str) -> bool:
    company_key = _company_key(company)
    if not company_key or not _has_debtor_assignments_table(db):
        return False
    return any(
        _company_key(empresa) == company_key
        for (empresa,) in db.query(DebtorUserAssignment.empresa).distinct().all()
    )


def can_operate_company(db: Session, user: User, company: str) -> bool:
    if is_privileged_operator(user):
        return True
    if str(user.role or "").strip().lower() != ROLE_EJECUTIVO:
        return False

    full_companies, owner_ids_by_company = executive_debtor_visibility_scope(
        db, int(user.id)
    )
    company_key = _company_key(company)
    return any(_company_key(item) == company_key for item in full_companies) or any(
        _company_key(item) == company_key for item in owner_ids_by_company
    )


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
    full_companies, owner_ids_by_company = executive_debtor_visibility_scope(
        db, int(user.id)
    )
    company_key = _company_key(company)
    owner_user_id = assigned_user_id_for_debtor(db, company, rut)
    if owner_user_id is None:
        if company_has_debtor_assignments(db, company):
            return False
        return any(_company_key(item) == company_key for item in full_companies)

    allowed_owner_ids: set[int] = set()
    for empresa, owner_ids in owner_ids_by_company.items():
        if _company_key(empresa) == company_key:
            allowed_owner_ids.update(owner_ids)
    return int(owner_user_id) in allowed_owner_ids


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
