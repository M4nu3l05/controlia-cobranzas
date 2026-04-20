from __future__ import annotations

import secrets
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import generate_salt, hash_password
from app.models.password_recovery_request import PasswordRecoveryRequest
from app.models.user import User
from app.schemas.user import (
    UserListItem,
    UserCarteraAssignmentItem,
    RecoveryRequestItem,
)
from app.services.auth_service import (
    ROLE_ADMIN,
    ROLE_SUPERVISOR,
    ROLES,
    create_user,
    get_user_by_id,
    validate_email,
    validate_password,
    validate_username,
)


def _role_label(role: str) -> str:
    return ROLES.get(role, role.capitalize())


def _to_user_item(user: User) -> UserListItem:
    return UserListItem(
        id=user.id,
        email=user.email,
        username=user.username,
        role=user.role,
        role_label=_role_label(user.role),
        is_active=bool(user.is_active),
        must_change_password=bool(user.must_change_password),
    )


def _count_admin_users(db: Session, active_only: bool = False) -> int:
    query = db.query(User).filter(User.role == ROLE_ADMIN)
    if active_only:
        query = query.filter(User.is_active.is_(True))
    return query.count()


def admin_list_users_service(db: Session) -> list[UserListItem]:
    rows = db.query(User).order_by(User.role.asc(), User.username.asc()).all()
    return [_to_user_item(row) for row in rows]


def admin_create_user_service(
    db: Session,
    *,
    executor: User,
    email: str,
    username: str,
    role: str,
    temp_password: str,
    confirm_password: str,
) -> UserListItem:
    if executor.role != ROLE_ADMIN:
        raise ValueError("No tienes permiso para crear usuarios.")

    errors: list[str] = []
    errors += validate_email(email)
    errors += validate_username(username)

    if role not in ROLES:
        errors.append(f"Rol no valido. Opciones: {', '.join(ROLES.keys())}")

    errors += validate_password(temp_password)
    if temp_password != confirm_password:
        errors.append("Las contrasenas no coinciden.")

    if errors:
        raise ValueError("\n".join(errors))

    user = create_user(
        db,
        email=email,
        username=username,
        password=temp_password,
        role=role,
        must_change_password=True,
    )
    return _to_user_item(user)


def admin_update_user_service(
    db: Session,
    *,
    executor: User,
    target_user_id: int,
    username: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
) -> UserListItem:
    if executor.role != ROLE_ADMIN:
        raise ValueError("No tienes permiso para editar usuarios.")

    user = get_user_by_id(db, target_user_id)
    if not user:
        raise ValueError("Usuario no encontrado.")

    if executor.id == target_user_id and role is not None and role != ROLE_ADMIN:
        raise ValueError("No puedes cambiar tu propio rol de administrador.")

    if username is not None:
        username_errors = validate_username(username)
        if username_errors:
            raise ValueError("\n".join(username_errors))
        user.username = username.strip()

    if role is not None:
        if role not in ROLES:
            raise ValueError(f"Rol no valido. Opciones: {', '.join(ROLES.keys())}")
        user.role = role

    if is_active is not None:
        if executor.id == target_user_id and not is_active:
            raise ValueError("No puedes desactivar tu propia cuenta.")

        if not is_active and user.role == ROLE_ADMIN and _count_admin_users(db, active_only=False) <= 1:
            raise ValueError("No puedes desactivar el ultimo administrador del sistema.")

        user.is_active = bool(is_active)

    db.add(user)
    db.commit()
    db.refresh(user)
    return _to_user_item(user)


def admin_delete_user_service(
    db: Session,
    *,
    executor: User,
    target_user_id: int,
) -> None:
    if executor.role != ROLE_ADMIN:
        raise ValueError("No tienes permiso para eliminar usuarios.")

    if executor.id == target_user_id:
        raise ValueError("No puedes eliminar tu propia cuenta.")

    user = get_user_by_id(db, target_user_id)
    if not user:
        raise ValueError("El usuario no existe o ya fue eliminado.")

    if user.role == ROLE_ADMIN and _count_admin_users(db, active_only=False) <= 1:
        raise ValueError("No puedes eliminar el ultimo administrador del sistema.")

    db.delete(user)
    db.commit()


def ensure_cartera_assignments_table(db: Session) -> None:
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS cartera_asignaciones (
            empresa TEXT PRIMARY KEY,
            user_id INTEGER NULL,
            email TEXT,
            username TEXT,
            updated_at TEXT,
            updated_by TEXT
        )
    """))
    db.commit()


def _ensure_can_manage_assignments(executor: User) -> None:
    if executor.role not in (ROLE_ADMIN, ROLE_SUPERVISOR):
        raise ValueError("No tienes permiso para gestionar asignaciones de cartera.")


def _ensure_can_view_assignments(executor: User, target_user_id: int) -> None:
    if executor.role in (ROLE_ADMIN, ROLE_SUPERVISOR):
        return
    if executor.id == int(target_user_id):
        return
    raise ValueError("No tienes permiso para consultar las carteras de otro usuario.")


def list_cartera_assignments_service(
    db: Session,
    *,
    executor: User,
) -> list[UserCarteraAssignmentItem]:
    _ensure_can_manage_assignments(executor)
    ensure_cartera_assignments_table(db)

    rows = db.execute(text("""
        SELECT empresa, user_id, email, username, updated_at, updated_by
        FROM cartera_asignaciones
        ORDER BY empresa
    """)).mappings().all()

    return [
        UserCarteraAssignmentItem(
            empresa=str(row.get("empresa") or "").strip(),
            user_id=int(row["user_id"]) if row.get("user_id") is not None else None,
            email=str(row.get("email") or "").strip(),
            username=str(row.get("username") or "").strip(),
            updated_at=str(row.get("updated_at") or "").strip(),
            updated_by=str(row.get("updated_by") or "").strip(),
        )
        for row in rows
    ]


def get_user_carteras_service(
    db: Session,
    *,
    executor: User,
    target_user_id: int,
) -> list[str]:
    _ensure_can_view_assignments(executor, target_user_id)
    ensure_cartera_assignments_table(db)

    rows = db.execute(
        text("""
            SELECT empresa
            FROM cartera_asignaciones
            WHERE user_id = :user_id
            ORDER BY empresa
        """),
        {"user_id": int(target_user_id)},
    ).fetchall()

    empresas: list[str] = []
    for row in rows:
        empresa = str(row[0] or "").strip()
        if empresa and empresa not in empresas:
            empresas.append(empresa)
    return empresas


def save_cartera_assignments_service(
    db: Session,
    *,
    executor: User,
    assignments: list[dict],
) -> list[UserCarteraAssignmentItem]:
    _ensure_can_manage_assignments(executor)
    ensure_cartera_assignments_table(db)

    if not assignments:
        db.execute(text("DELETE FROM cartera_asignaciones"))
        db.commit()
        return []

    seen_empresas: set[str] = set()

    for raw in assignments:
        empresa = str((raw or {}).get("empresa") or "").strip()
        if not empresa or empresa in seen_empresas:
            continue
        seen_empresas.add(empresa)

        user_id = (raw or {}).get("user_id")
        if user_id in (None, "", 0, "0"):
            db.execute(
                text("DELETE FROM cartera_asignaciones WHERE empresa = :empresa"),
                {"empresa": empresa},
            )
            continue

        user = get_user_by_id(db, int(user_id))
        if not user:
            raise ValueError(f"El usuario indicado para '{empresa}' no existe.")
        if user.role != "ejecutivo":
            raise ValueError(f"Solo puedes asignar carteras a usuarios con rol ejecutivo. Problema en '{empresa}'.")
        if not bool(user.is_active):
            raise ValueError(f"No puedes asignar '{empresa}' a un usuario inactivo.")

        db.execute(
            text("""
                INSERT INTO cartera_asignaciones (
                    empresa, user_id, email, username, updated_at, updated_by
                ) VALUES (
                    :empresa, :user_id, :email, :username, CURRENT_TIMESTAMP, :updated_by
                )
                ON CONFLICT(empresa) DO UPDATE SET
                    user_id = excluded.user_id,
                    email = excluded.email,
                    username = excluded.username,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_by = excluded.updated_by
            """),
            {
                "empresa": empresa,
                "user_id": int(user.id),
                "email": str(user.email or "").strip(),
                "username": str(user.username or "").strip(),
                "updated_by": str(executor.username or "").strip(),
            },
        )

    db.commit()
    return list_cartera_assignments_service(db, executor=executor)


def get_current_user_carteras_service(
    db: Session,
    *,
    executor: User,
) -> list[str]:
    return get_user_carteras_service(
        db=db,
        executor=executor,
        target_user_id=int(executor.id),
    )


def _required_assistor_role_for_target(target_role: str) -> str:
    role = str(target_role or "").strip().lower()
    if role == "ejecutivo":
        return ROLE_SUPERVISOR
    if role == "supervisor":
        return ROLE_ADMIN
    return ""


def _can_executor_assist_target(*, executor: User, target: User) -> bool:
    required = _required_assistor_role_for_target(str(target.role or ""))
    if not required:
        return False

    executor_role = str(executor.role or "").strip().lower()
    if required == ROLE_SUPERVISOR:
        return executor_role == ROLE_SUPERVISOR
    if required == ROLE_ADMIN:
        return executor_role == ROLE_ADMIN
    return False


def _generate_temp_password() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789@#$%"
    base = "".join(secrets.choice(alphabet) for _ in range(12))
    return f"A9@{base}"


def assisted_reset_password_service(
    db: Session,
    *,
    executor: User,
    target_user_id: int,
) -> tuple[UserListItem, str]:
    target = get_user_by_id(db, int(target_user_id))
    if not target:
        raise ValueError("Usuario no encontrado.")

    if int(executor.id) == int(target.id):
        raise ValueError("No puedes usar recuperacion asistida sobre tu propia cuenta.")

    if not bool(target.is_active):
        raise ValueError("No se puede recuperar una cuenta inactiva.")

    if not _can_executor_assist_target(executor=executor, target=target):
        raise ValueError(
            "No tienes permiso para recuperar esta cuenta. "
            "Regla: ejecutivo -> solo supervisor | supervisor -> solo admin."
        )

    temp_password = _generate_temp_password()
    salt = generate_salt()
    target.salt = salt
    target.password_hash = hash_password(temp_password, salt)
    target.must_change_password = True

    pending_rows = (
        db.query(PasswordRecoveryRequest)
        .filter(
            PasswordRecoveryRequest.target_user_id == int(target.id),
            PasswordRecoveryRequest.status == "pending",
        )
        .all()
    )
    for req in pending_rows:
        req.status = "resolved"
        req.resolved_by_user_id = int(executor.id)
        req.resolution_note = "Recuperacion asistida completada"
        req.resolved_at = datetime.now()
        db.add(req)

    db.add(target)
    db.commit()
    db.refresh(target)

    return _to_user_item(target), temp_password


def _ensure_admin_or_supervisor(executor: User) -> None:
    if str(executor.role or "").strip().lower() not in {ROLE_ADMIN, ROLE_SUPERVISOR}:
        raise ValueError("No tienes permiso para gestionar recuperaciones asistidas.")


def list_pending_recovery_requests_service(
    db: Session,
    *,
    executor: User,
) -> list[RecoveryRequestItem]:
    _ensure_admin_or_supervisor(executor)
    executor_role = str(executor.role or "").strip().lower()

    rows = (
        db.query(PasswordRecoveryRequest)
        .filter(
            PasswordRecoveryRequest.status == "pending",
            PasswordRecoveryRequest.required_assistor_role == executor_role,
        )
        .order_by(PasswordRecoveryRequest.requested_at.asc(), PasswordRecoveryRequest.id.asc())
        .all()
    )

    out: list[RecoveryRequestItem] = []
    for row in rows:
        target = get_user_by_id(db, int(row.target_user_id)) if row.target_user_id else None
        out.append(
            RecoveryRequestItem(
                id=int(row.id),
                requested_email=str(row.requested_email or ""),
                target_user_id=(int(row.target_user_id) if row.target_user_id is not None else None),
                target_username=str(getattr(target, "username", "") or ""),
                target_role=str(getattr(target, "role", row.target_role) or ""),
                target_role_label=_role_label(str(getattr(target, "role", row.target_role) or "")),
                required_assistor_role=str(row.required_assistor_role or ""),
                requested_at=row.requested_at.strftime("%Y-%m-%d %H:%M:%S") if row.requested_at else "",
                status=str(row.status or "pending"),
            )
        )
    return out


def assisted_reset_password_by_request_service(
    db: Session,
    *,
    executor: User,
    request_id: int,
) -> tuple[int, UserListItem, str]:
    _ensure_admin_or_supervisor(executor)
    executor_role = str(executor.role or "").strip().lower()

    req = (
        db.query(PasswordRecoveryRequest)
        .filter(
            PasswordRecoveryRequest.id == int(request_id),
            PasswordRecoveryRequest.status == "pending",
            PasswordRecoveryRequest.required_assistor_role == executor_role,
        )
        .first()
    )
    if not req:
        raise ValueError("La solicitud ya no está pendiente o no te corresponde gestionarla.")
    if not req.target_user_id:
        raise ValueError("La solicitud no tiene usuario objetivo válido.")

    user_item, temp_password = assisted_reset_password_service(
        db=db,
        executor=executor,
        target_user_id=int(req.target_user_id),
    )
    return int(req.id), user_item, temp_password





