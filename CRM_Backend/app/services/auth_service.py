from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.core.security import create_access_token, generate_salt, hash_password, verify_password
from app.models.password_recovery_request import PasswordRecoveryRequest
from app.models.reset_token import PasswordResetToken
from app.models.user import User
from app.schemas.auth import TokenResponse, UserMeResponse
from app.services.session_history_service import register_session_login

ROLES = {
    "admin": "Administrador",
    "supervisor": "Supervisor",
    "ejecutivo": "Ejecutivo",
}

ROLE_ADMIN = "admin"
ROLE_SUPERVISOR = "supervisor"
ROLE_EJECUTIVO = "ejecutivo"

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
_RESET_EXPIRY_MINUTES = 15


def role_label(role: str) -> str:
    return ROLES.get(role, role.capitalize())


def validate_email(email: str) -> list[str]:
    errors: list[str] = []
    if not email.strip():
        errors.append("El correo no puede estar vacio.")
    elif not _EMAIL_RE.match(email.strip()):
        errors.append("El formato del correo no es valido.")
    return errors


def validate_password(password: str) -> list[str]:
    errors: list[str] = []
    if len(password) < 8:
        errors.append("Minimo 8 caracteres.")
    if not re.search(r"[A-Z]", password):
        errors.append("Debe incluir al menos una mayuscula.")
    if not re.search(r"[a-z]", password):
        errors.append("Debe incluir al menos una minuscula.")
    if not re.search(r"\d", password):
        errors.append("Debe incluir al menos un numero.")
    return errors


def validate_username(username: str) -> list[str]:
    errors: list[str] = []
    s = username.strip()
    if not s:
        errors.append("El nombre no puede estar vacio.")
    elif len(s) < 2:
        errors.append("Minimo 2 caracteres.")
    elif len(s) > 60:
        errors.append("Maximo 60 caracteres.")
    return errors


def user_to_me(user: User) -> UserMeResponse:
    return UserMeResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        role=user.role,
        role_label=role_label(user.role),
        is_active=bool(user.is_active),
        must_change_password=bool(user.must_change_password),
    )


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    email_norm = email.strip().lower()
    return db.query(User).filter(User.email == email_norm).first()


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    return db.query(User).filter(User.id == user_id).first()


def create_user(
    db: Session,
    *,
    email: str,
    username: str,
    password: str,
    role: str = ROLE_EJECUTIVO,
    must_change_password: bool = False,
) -> User:
    if role not in ROLES:
        raise ValueError(f"Rol no valido: {role}")

    email_norm = email.strip().lower()

    if get_user_by_email(db, email_norm):
        raise ValueError(f"El correo '{email_norm}' ya esta registrado.")

    salt = generate_salt()
    password_hash = hash_password(password, salt)

    user = User(
        email=email_norm,
        username=username.strip(),
        password_hash=password_hash,
        salt=salt,
        role=role,
        is_active=True,
        must_change_password=must_change_password,
    )

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> TokenResponse:
    errs = validate_email(email)
    if errs:
        raise ValueError(errs[0])

    user = get_user_by_email(db, email)
    if not user:
        raise ValueError("Correo o contrasena incorrectos.")

    if not user.is_active:
        raise ValueError("Esta cuenta esta desactivada. Contacta al administrador.")

    if not verify_password(password, user.salt, user.password_hash):
        raise ValueError("Correo o contrasena incorrectos.")

    token = create_access_token(subject=str(user.id))
    session_row = register_session_login(db, user=user, auth_source="backend")

    return TokenResponse(
        access_token=token,
        must_change_password=bool(user.must_change_password),
        session_history_id=int(session_row.id),
        user=user_to_me(user),
    )


def change_current_user_password(
    db: Session,
    *,
    user: User,
    new_password: str,
    confirm_password: str,
) -> User:
    errors = validate_password(new_password)
    if new_password != confirm_password:
        errors.append("Las contrasenas no coinciden.")
    if errors:
        raise ValueError("\n".join(errors))

    user.salt = generate_salt()
    user.password_hash = hash_password(new_password, user.salt)
    user.must_change_password = False

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_password_reset_token(db: Session, *, email: str) -> tuple[str, str]:
    errs = validate_email(email)
    if errs:
        raise ValueError(errs[0])

    user = get_user_by_email(db, email)
    if not user or not bool(user.is_active):
        return "", "Si el correo esta registrado, recibirás respuesta por el canal autorizado."

    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == int(user.id),
        PasswordResetToken.used == False,  # noqa: E712
    ).update({"used": True}, synchronize_session=False)

    token = str(secrets.randbelow(900_000) + 100_000)
    row = PasswordResetToken(
        user_id=int(user.id),
        token=token,
        expires_at=datetime.now() + timedelta(minutes=_RESET_EXPIRY_MINUTES),
        used=False,
    )
    db.add(row)
    db.commit()
    return token, ""


def _required_assistor_role_for_target(target_role: str) -> str:
    role = str(target_role or "").strip().lower()
    if role == ROLE_EJECUTIVO:
        return ROLE_SUPERVISOR
    if role == ROLE_SUPERVISOR:
        return ROLE_ADMIN
    return ""


def create_assisted_recovery_request(db: Session, *, email: str) -> str:
    errs = validate_email(email)
    if errs:
        raise ValueError(errs[0])

    email_norm = email.strip().lower()
    user = get_user_by_email(db, email_norm)

    target_user_id: int | None = None
    target_role = ""
    required_role = ""

    if user and bool(user.is_active):
        target_user_id = int(user.id)
        target_role = str(user.role or "").strip()
        required_role = _required_assistor_role_for_target(target_role)

    row = PasswordRecoveryRequest(
        requested_email=email_norm,
        target_user_id=target_user_id,
        target_role=target_role,
        required_assistor_role=required_role,
        status="pending",
    )
    db.add(row)
    db.commit()

    return (
        "Solicitud registrada. "
        "Tu recuperacion sera gestionada por el rol autorizado segun tu perfil."
    )


def confirm_password_reset(
    db: Session,
    *,
    email: str,
    token: str,
    new_password: str,
    confirm_password: str,
) -> None:
    errs = validate_email(email)
    errs += validate_password(new_password)
    if new_password != confirm_password:
        errs.append("Las contrasenas no coinciden.")
    if errs:
        raise ValueError("\n".join(errs))

    user = get_user_by_email(db, email)
    if not user:
        raise ValueError("Codigo invalido o expirado. Solicita uno nuevo.")

    now = datetime.now()
    row = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.user_id == int(user.id),
            PasswordResetToken.token == str(token).strip(),
            PasswordResetToken.used == False,  # noqa: E712
            PasswordResetToken.expires_at > now,
        )
        .order_by(PasswordResetToken.id.desc())
        .first()
    )
    if not row:
        raise ValueError("Codigo invalido o expirado. Solicita uno nuevo.")

    user.salt = generate_salt()
    user.password_hash = hash_password(new_password, user.salt)
    user.must_change_password = False
    row.used = True

    db.add(user)
    db.add(row)
    db.commit()


def ensure_first_admin(
    db: Session,
    *,
    email: str,
    username: str,
    password: str,
) -> User:
    existing = db.query(User).count()
    if existing > 0:
        return db.query(User).filter(User.role == ROLE_ADMIN).first()

    user = create_user(
        db,
        email=email,
        username=username,
        password=password,
        role=ROLE_ADMIN,
        must_change_password=True,
    )
    return user
