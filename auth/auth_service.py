# ================================================================
#  auth/auth_service.py
#  Login, cambio forzado, usuarios, deudores y gestiones conectados a CRM_Backend.
# ================================================================

from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from core.paths import get_config_dir

from .auth_db import (
    ROLE_ADMIN, ROLE_SUPERVISOR, ROLE_EJECUTIVO, ROLES,
    create_reset_token,
    delete_setup_credentials_file,
    get_user_by_email,
    mark_token_used,
    update_password,
    validate_reset_token,
)

__all__ = [
    "UserSession",
    "ROLE_ADMIN", "ROLE_SUPERVISOR", "ROLE_EJECUTIVO", "ROLES",
    "login", "admin_create_user", "request_password_reset",
    "confirm_password_reset", "force_change_password",
    "validate_email", "validate_password", "validate_username",
    "password_strength", "list_users", "toggle_user_active",
    "admin_update_user", "admin_delete_user",
    "backend_list_deudores", "backend_get_deudor_detalle",
    "backend_list_destinatarios",
    "backend_import_deudores",
    "backend_list_gestiones", "backend_create_gestion", "backend_delete_gestion", "backend_register_pago", "backend_update_deudor_cliente",
    "backend_list_mis_gestiones_asignadas", "backend_marcar_gestion_asignada_realizada",
    "backend_get_user_carteras", "backend_list_cartera_asignaciones", "backend_save_cartera_asignaciones", "backend_list_all_gestiones",
    "backend_clear_empresa_deudores", "backend_clear_all_deudores", "backend_clear_all_gestiones",
    "backend_get_legal_acceptance_status", "backend_register_legal_acceptance", "backend_assisted_reset_password",
    "backend_list_pending_recovery_requests", "backend_reset_pending_recovery_request",
    "backend_list_email_templates", "backend_create_email_template",
    "backend_update_email_template", "backend_delete_email_template",
    "backend_close_session",
]

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
DEFAULT_BACKEND_URL = "https://crm-backend-4712.onrender.com"
DEFAULT_TIMEOUT = 12
_HTTP_POOL_SIZE = 20
_CARTERA_ASSIGNMENTS_TTL_SEC = 120
_HTTP_SESSION = requests.Session()
_HTTP_SESSION.mount("http://", HTTPAdapter(pool_connections=_HTTP_POOL_SIZE, pool_maxsize=_HTTP_POOL_SIZE))
_HTTP_SESSION.mount("https://", HTTPAdapter(pool_connections=_HTTP_POOL_SIZE, pool_maxsize=_HTTP_POOL_SIZE))


@dataclass
class UserSession:
    user_id: int
    email: str
    username: str
    role: str
    is_active: bool
    must_change_password: bool
    access_token: str | None = None
    auth_source: str = "local"
    empresas_asignadas: list[str] | None = None
    session_history_id: int | None = None

    @property
    def role_label(self) -> str:
        return ROLES.get(self.role, self.role.capitalize())

    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    def is_supervisor_or_above(self) -> bool:
        return self.role in (ROLE_ADMIN, ROLE_SUPERVISOR)

    def is_ejecutivo(self) -> bool:
        return self.role == ROLE_EJECUTIVO

    @classmethod
    def from_backend(cls, payload: dict) -> "UserSession":
        user = payload.get("user") or {}
        return cls(
            user_id=int(user.get("id")),
            email=str(user.get("email", "")),
            username=str(user.get("username", "")),
            role=str(user.get("role", ROLE_EJECUTIVO)),
            is_active=bool(user.get("is_active", True)),
            must_change_password=bool(payload.get("must_change_password", user.get("must_change_password", False))),
            access_token=str(payload.get("access_token", "")) or None,
            auth_source="backend",
            empresas_asignadas=[],
            session_history_id=(
                int(payload.get("session_history_id"))
                if payload.get("session_history_id") is not None
                else None
            ),
        )


def get_backend_base_url() -> str:
    # 1) Variable de entorno (prioridad mayor).
    env_value = os.environ.get("CONTROLIA_BACKEND_URL", "").strip()
    if env_value:
        return env_value.rstrip("/")

    # 2) Archivo junto al ejecutable instalado (Program Files).
    try:
        exe_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
        exe_cfg = exe_dir / "backend_url.txt"
        if exe_cfg.exists():
            txt = exe_cfg.read_text(encoding="utf-8", errors="ignore").strip()
            if txt:
                return txt.rstrip("/")
    except OSError:
        pass

    # 3) Archivo de configuración en runtime (%APPDATA%/Controlia Cobranzas/config).
    try:
        cfg_path = get_config_dir() / "backend_url.txt"
        if cfg_path.exists():
            txt = cfg_path.read_text(encoding="utf-8", errors="ignore").strip()
            if txt:
                return txt.rstrip("/")
    except OSError:
        pass

    # 4) Fallback por defecto (backend productivo).
    return DEFAULT_BACKEND_URL.rstrip("/")


def _friendly_backend_error(exc: Exception) -> str:
    if isinstance(exc, requests.Timeout):
        return "El servidor tardó demasiado en responder. Verifica que el backend esté encendido."
    if isinstance(exc, requests.ConnectionError):
        return (
            "No fue posible conectar con el servidor del CRM. "
            "Verifica que CRM_Backend esté ejecutándose y que la URL sea correcta."
        )
    return "Ocurrió un problema al conectar con el servidor del CRM."


def _friendly_http_status_error(status_code: int, detail: str = "") -> str:
    detail_txt = str(detail or "").strip()
    detail_norm = detail_txt.lower()

    if status_code == 401:
        return "Tu sesión expiró o ya no es válida. Cierra sesión e ingresa nuevamente."
    if status_code == 403:
        return detail_txt or "No tienes permisos para realizar esta acción."
    if status_code == 404:
        return detail_txt or "No se encontró el recurso solicitado en el servidor."
    if status_code == 422:
        return detail_txt or "La solicitud contiene datos inválidos o incompletos."
    if status_code >= 500:
        return "El servidor del CRM presentó un error interno. Intenta nuevamente en unos minutos."
    if "token" in detail_norm or "credentials" in detail_norm or "credenciales" in detail_norm:
        return "Tu sesión expiró o ya no es válida. Cierra sesión e ingresa nuevamente."
    return detail_txt or f"Error HTTP {status_code} al consultar el backend."


def _extract_error_message(response: requests.Response, default_message: str) -> str:
    try:
        data = response.json()
    except ValueError:
        return _friendly_http_status_error(response.status_code, default_message)

    detail = data.get("detail")
    if isinstance(detail, str) and detail.strip():
        return _friendly_http_status_error(response.status_code, detail.strip())
    if isinstance(detail, list) and detail:
        parts: list[str] = []
        for item in detail:
            if isinstance(item, dict):
                loc = item.get("loc") or []
                msg = str(item.get("msg", "")).strip()
                where = " > ".join(str(x) for x in loc if x not in ("body",))
                if where and msg:
                    parts.append(f"{where}: {msg}")
                elif msg:
                    parts.append(msg)
            elif str(item).strip():
                parts.append(str(item).strip())
        return _friendly_http_status_error(response.status_code, " | ".join(parts))
    return _friendly_http_status_error(response.status_code, default_message)


def _http_post_json(path: str, payload: dict, timeout: int = DEFAULT_TIMEOUT) -> dict:
    url = f"{get_backend_base_url()}{path}"
    response = _HTTP_SESSION.post(url, json=payload, timeout=timeout)
    try:
        data = response.json()
    except ValueError:
        data = {}

    if response.status_code >= 400:
        detail = data.get("detail")
        if path == "/auth/login" and response.status_code in (400, 401):
            detail_txt = str(detail or "").strip().lower()
            if "inactiv" in detail_txt:
                raise ValueError("Tu cuenta está inactiva. Contacta al administrador.")
            raise ValueError("Usuario o contraseña incorrectos.")
        if isinstance(detail, str) and detail.strip():
            raise ValueError(_friendly_http_status_error(response.status_code, detail.strip()))
        raise ValueError(_friendly_http_status_error(response.status_code))

    return data


def _http_request_auth(
    method: str,
    path: str,
    token: str,
    payload: dict | None = None,
    params: dict | None = None,
    timeout: int = DEFAULT_TIMEOUT,
):
    url = f"{get_backend_base_url()}{path}"
    response = _HTTP_SESSION.request(
        method=method,
        url=url,
        json=payload,
        params=params,
        timeout=timeout,
        headers={"Authorization": f"Bearer {token}"},
    )

    if response.status_code >= 400:
        raise ValueError(_extract_error_message(response, f"Error HTTP {response.status_code} al consultar el backend."))

    if response.content:
        try:
            return response.json()
        except ValueError:
            return {}
    return {}


def _http_multipart_auth(
    path: str,
    token: str,
    *,
    data: dict,
    files: dict,
    timeout: int = 120,
) -> dict:
    url = f"{get_backend_base_url()}{path}"
    response = _HTTP_SESSION.post(
        url=url,
        data=data,
        files=files,
        timeout=timeout,
        headers={"Authorization": f"Bearer {token}"},
    )

    if response.status_code >= 400:
        raise ValueError(_extract_error_message(response, f"Error HTTP {response.status_code} al consultar el backend."))

    try:
        return response.json()
    except ValueError:
        return {}


def _require_backend_token(session: UserSession) -> str:
    token = getattr(session, "access_token", None)
    if not token:
        raise ValueError("La sesión no contiene token de autenticación.")
    return token


def validate_email(email: str) -> List[str]:
    errors = []
    if not email.strip():
        errors.append("El correo no puede estar vacío.")
    elif not _EMAIL_RE.match(email.strip()):
        errors.append("El formato del correo no es válido.")
    return errors


def validate_password(password: str) -> List[str]:
    errors = []
    if len(password) < 8:
        errors.append("Mínimo 8 caracteres.")
    if not re.search(r"[A-Z]", password):
        errors.append("Debe incluir al menos una mayúscula.")
    if not re.search(r"[a-z]", password):
        errors.append("Debe incluir al menos una minúscula.")
    if not re.search(r"\d", password):
        errors.append("Debe incluir al menos un número.")
    return errors


def validate_username(username: str) -> List[str]:
    errors = []
    s = username.strip()
    if not s:
        errors.append("El nombre no puede estar vacío.")
    elif len(s) < 2:
        errors.append("Mínimo 2 caracteres.")
    elif len(s) > 60:
        errors.append("Máximo 60 caracteres.")
    return errors


def password_strength(password: str) -> Tuple[int, str]:
    score = 0
    if len(password) >= 8:
        score += 25
    if len(password) >= 12:
        score += 10
    if re.search(r"[A-Z]", password):
        score += 20
    if re.search(r"[a-z]", password):
        score += 20
    if re.search(r"\d", password):
        score += 15
    if re.search(r"[^A-Za-z0-9]", password):
        score += 10
    score = min(score, 100)
    label = (
        "Débil" if score < 40 else
        "Media" if score < 70 else
        "Fuerte" if score < 90 else
        "Muy fuerte"
    )
    return score, label


def login(email: str, password: str) -> Tuple[Optional[UserSession], str]:
    errs = validate_email(email)
    if errs:
        return None, errs[0]

    if not password:
        return None, "Ingresa tu contraseña."

    try:
        data = _http_post_json(
            "/auth/login",
            {"email": email.strip(), "password": password},
        )
        session = UserSession.from_backend(data)

        if session.is_ejecutivo():
            empresas, _ = backend_get_user_carteras(session, user_id=session.user_id)
            session.empresas_asignadas = empresas

        return session, ""
    except ValueError as exc:
        return None, str(exc)
    except requests.RequestException as exc:
        return None, _friendly_backend_error(exc)


def force_change_password(
    session: UserSession,
    new_password: str,
    confirm_password: str,
) -> List[str]:
    errors = validate_password(new_password)
    if new_password != confirm_password:
        errors.append("Las contraseñas no coinciden.")
    if errors:
        return errors

    if getattr(session, "auth_source", "") == "backend":
        try:
            _http_request_auth(
                "POST",
                "/auth/change-password",
                token=_require_backend_token(session),
                payload={
                    "new_password": new_password,
                    "confirm_password": confirm_password,
                },
            )
            session.must_change_password = False
            return []
        except ValueError as exc:
            return [str(exc)]
        except requests.RequestException as exc:
            return [_friendly_backend_error(exc)]

    update_password(session.user_id, new_password, must_change=False)
    delete_setup_credentials_file()
    return []


def admin_create_user(
    executor: UserSession,
    email: str,
    username: str,
    role: str,
    temp_password: str,
    confirm_password: str,
) -> Tuple[Optional[dict], List[str]]:
    if not executor.is_admin():
        return None, ["No tienes permiso para crear usuarios."]

    errors: List[str] = []
    errors += validate_email(email)
    errors += validate_username(username)

    if role not in ROLES:
        errors.append(f"Rol no válido. Opciones: {', '.join(ROLES.keys())}")

    errors += validate_password(temp_password)
    if temp_password != confirm_password:
        errors.append("Las contraseñas no coinciden.")

    if errors:
        return None, errors

    if getattr(executor, "auth_source", "") == "backend":
        try:
            data = _http_request_auth(
                "POST",
                "/users",
                token=_require_backend_token(executor),
                payload={
                    "email": email.strip(),
                    "username": username.strip(),
                    "role": role,
                    "temp_password": temp_password,
                    "confirm_password": confirm_password,
                },
            )
            return data, []
        except ValueError as exc:
            return None, [str(exc)]
        except requests.RequestException as exc:
            return None, [_friendly_backend_error(exc)]

    return None, ["La creación local de usuarios ya no está habilitada en este flujo."]


def list_users(session: UserSession) -> List[dict]:
    if getattr(session, "auth_source", "") == "backend":
        try:
            data = _http_request_auth(
                "GET",
                "/users",
                token=_require_backend_token(session),
            )
            return data if isinstance(data, list) else []
        except ValueError:
            return []
        except requests.RequestException:
            return []

    return []


def admin_update_user(
    executor: UserSession,
    target_user_id: int,
    username: str = None,
    role: str = None,
    is_active: bool = None,
) -> List[str]:
    if not executor.is_admin():
        return ["No tienes permiso para editar usuarios."]

    if getattr(executor, "auth_source", "") == "backend":
        try:
            payload = {}
            if username is not None:
                payload["username"] = username
            if role is not None:
                payload["role"] = role
            if is_active is not None:
                payload["is_active"] = bool(is_active)

            _http_request_auth(
                "PUT",
                f"/users/{target_user_id}",
                token=_require_backend_token(executor),
                payload=payload,
            )
            return []
        except ValueError as exc:
            return [str(exc)]
        except requests.RequestException as exc:
            return [_friendly_backend_error(exc)]

    return ["La edición local de usuarios ya no está habilitada en este flujo."]


def toggle_user_active(
    executor: UserSession,
    target_user_id: int,
    current_is_active: bool,
) -> List[str]:
    return admin_update_user(
        executor,
        target_user_id,
        is_active=not bool(current_is_active),
    )


def admin_delete_user(
    executor: UserSession,
    target_user_id: int,
) -> List[str]:
    if not executor.is_admin():
        return ["No tienes permiso para eliminar usuarios."]

    if getattr(executor, "auth_source", "") == "backend":
        try:
            _http_request_auth(
                "DELETE",
                f"/users/{target_user_id}",
                token=_require_backend_token(executor),
            )
            return []
        except ValueError as exc:
            return [str(exc)]
        except requests.RequestException as exc:
            return [_friendly_backend_error(exc)]

    return ["La eliminación local de usuarios ya no está habilitada en este flujo."]


def backend_list_deudores(
    session: UserSession,
    *,
    q: str = "",
    empresa: str = "",
    periodo_carga: str = "",
    limit: int = 5000,
) -> Tuple[list[dict], str]:
    try:
        data = _http_request_auth(
            "GET",
            "/deudores",
            token=_require_backend_token(session),
            params={
                "q": q.strip(),
                "empresa": empresa.strip(),
                "periodo_carga": periodo_carga.strip(),
                "limit": max(1, min(int(limit), 5000)),
            },
        )
        items = data.get("items", []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else [], ""
    except ValueError as exc:
        return [], str(exc)
    except requests.RequestException as exc:
        return [], _friendly_backend_error(exc)


def backend_list_destinatarios(
    session: UserSession,
    *,
    empresa: str = "",
    periodo_carga: str = "",
    limit: int = 50000,
) -> Tuple[list[dict], str]:
    try:
        data = _http_request_auth(
            "GET",
            "/deudores/destinatarios",
            token=_require_backend_token(session),
            params={
                "empresa": empresa.strip(),
                "periodo_carga": periodo_carga.strip(),
                "limit": max(1, min(int(limit), 50000)),
            },
        )
        return data if isinstance(data, list) else [], ""
    except ValueError as exc:
        return [], str(exc)
    except requests.RequestException as exc:
        return [], _friendly_backend_error(exc)


def backend_get_deudor_detalle(
    session: UserSession,
    *,
    rut: str,
    empresa: str = "",
) -> Tuple[dict | None, str]:
    try:
        data = _http_request_auth(
            "GET",
            f"/deudores/{rut}",
            token=_require_backend_token(session),
            params={"empresa": empresa.strip()},
        )
        return data if isinstance(data, dict) else None, ""
    except ValueError as exc:
        return None, str(exc)
    except requests.RequestException as exc:
        return None, _friendly_backend_error(exc)


def backend_import_deudores(
    session: UserSession,
    *,
    empresa: str,
    excel_path: str,
) -> Tuple[dict | None, str]:
    try:
        token = _require_backend_token(session)
        filename = os.path.basename(excel_path)
        with open(excel_path, "rb") as fh:
            data = _http_multipart_auth(
                "/deudores/import",
                token=token,
                data={"empresa": empresa},
                files={
                    "file": (
                        filename,
                        fh,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )
        return data if isinstance(data, dict) else None, ""
    except ValueError as exc:
        return None, str(exc)
    except requests.RequestException as exc:
        return None, _friendly_backend_error(exc)
    except OSError as exc:
        return None, f"No se pudo abrir el archivo Excel: {exc}"


def backend_clear_empresa_deudores(session: UserSession, *, empresa: str) -> str:
    try:
        data = _http_request_auth(
            "DELETE",
            f"/deudores/empresa/{empresa.strip()}",
            token=_require_backend_token(session),
        )
        if isinstance(data, dict):
            return str(data.get("message", "")).strip()
        return ""
    except ValueError as exc:
        return str(exc)
    except requests.RequestException as exc:
        return _friendly_backend_error(exc)


def backend_clear_all_deudores(session: UserSession) -> str:
    try:
        data = _http_request_auth(
            "DELETE",
            "/deudores",
            token=_require_backend_token(session),
        )
        if isinstance(data, dict):
            return str(data.get("message", "")).strip()
        return ""
    except ValueError as exc:
        return str(exc)
    except requests.RequestException as exc:
        return _friendly_backend_error(exc)


def backend_clear_all_gestiones(session: UserSession) -> str:
    try:
        data = _http_request_auth(
            "DELETE",
            "/gestiones",
            token=_require_backend_token(session),
        )
        if isinstance(data, dict):
            return str(data.get("message", "")).strip()
        return ""
    except ValueError as exc:
        return str(exc)
    except requests.RequestException as exc:
        return _friendly_backend_error(exc)


def backend_list_gestiones(
    session: UserSession,
    *,
    rut: str,
    empresa: str = "",
) -> Tuple[list[dict], str]:
    try:
        data = _http_request_auth(
            "GET",
            f"/deudores/{rut}/gestiones",
            token=_require_backend_token(session),
            params={"empresa": empresa.strip()},
        )
        return data if isinstance(data, list) else [], ""
    except ValueError as exc:
        return [], str(exc)
    except requests.RequestException as exc:
        return [], _friendly_backend_error(exc)


def backend_list_all_gestiones(
    session: UserSession,
    *,
    empresa: str = "",
    fecha_desde: str = "",
    fecha_hasta: str = "",
) -> Tuple[list[dict], str]:
    try:
        data = _http_request_auth(
            "GET",
            "/gestiones",
            token=_require_backend_token(session),
            params={
                "empresa": empresa.strip(),
                "fecha_desde": fecha_desde.strip(),
                "fecha_hasta": fecha_hasta.strip(),
            },
        )
        return data if isinstance(data, list) else [], ""
    except ValueError as exc:
        return [], str(exc)
    except requests.RequestException as exc:
        return [], _friendly_backend_error(exc)


def backend_create_gestion(
    session: UserSession,
    *,
    rut: str,
    empresa: str,
    nombre_afiliado: str,
    tipo_gestion: str,
    estado: str,
    fecha_gestion: str,
    observacion: str = "",
    origen: str = "manual",
    assigned_to_user_id: int | None = None,
) -> Tuple[dict | None, str]:
    try:
        data = _http_request_auth(
            "POST",
            f"/deudores/{rut}/gestiones",
            token=_require_backend_token(session),
            payload={
                "empresa": empresa.strip(),
                "nombre_afiliado": nombre_afiliado.strip(),
                "tipo_gestion": tipo_gestion,
                "estado": estado,
                "fecha_gestion": fecha_gestion,
                "observacion": observacion,
                "origen": origen,
                "assigned_to_user_id": assigned_to_user_id,
            },
        )
        return data if isinstance(data, dict) else None, ""
    except ValueError as exc:
        return None, str(exc)
    except requests.RequestException as exc:
        return None, _friendly_backend_error(exc)


def backend_delete_gestion(
    session: UserSession,
    *,
    gestion_id: int,
) -> str:
    try:
        _http_request_auth(
            "DELETE",
            f"/gestiones/{int(gestion_id)}",
            token=_require_backend_token(session),
        )
        return ""
    except ValueError as exc:
        return str(exc)
    except requests.RequestException as exc:
        return _friendly_backend_error(exc)


def backend_list_mis_gestiones_asignadas(
    session: UserSession,
) -> Tuple[list[dict], str]:
    try:
        data = _http_request_auth(
            "GET",
            "/gestiones/asignadas/me",
            token=_require_backend_token(session),
        )
        return data if isinstance(data, list) else [], ""
    except ValueError as exc:
        return [], str(exc)
    except requests.RequestException as exc:
        return [], _friendly_backend_error(exc)


def backend_marcar_gestion_asignada_realizada(
    session: UserSession,
    *,
    gestion_id: int,
) -> Tuple[dict | None, str]:
    try:
        data = _http_request_auth(
            "POST",
            f"/gestiones/{int(gestion_id)}/marcar-realizada",
            token=_require_backend_token(session),
        )
        return data if isinstance(data, dict) else None, ""
    except ValueError as exc:
        return None, str(exc)
    except requests.RequestException as exc:
        return None, _friendly_backend_error(exc)


def backend_register_pago(
    session: UserSession,
    *,
    rut: str,
    empresa: str,
    expediente: str,
    tipo_pago: str,
    monto: float,
    observaciones: str = "",
) -> Tuple[dict | None, str]:
    try:
        data = _http_request_auth(
            "POST",
            f"/deudores/{rut}/pagos",
            token=_require_backend_token(session),
            payload={
                "empresa": empresa.strip(),
                "expediente": expediente.strip(),
                "tipo_pago": tipo_pago,
                "monto": float(monto),
                "observaciones": observaciones,
            },
        )
        return data if isinstance(data, dict) else None, ""
    except ValueError as exc:
        return None, str(exc)
    except requests.RequestException as exc:
        return None, _friendly_backend_error(exc)


def request_password_reset(email: str) -> Tuple[Optional[str], str]:
    errs = validate_email(email)
    if errs:
        return None, errs[0]
    user = get_user_by_email(email)
    if not user:
        return None, "Si el correo está registrado, recibirás el código."
    token = create_reset_token(user["id"])
    return token, ""


def confirm_password_reset(
    email: str, token: str, new_password: str, confirm_password: str
) -> List[str]:
    errors = validate_password(new_password)
    if new_password != confirm_password:
        errors.append("Las contraseñas no coinciden.")
    if errors:
        return errors
    user = validate_reset_token(email, token)
    if not user:
        return ["Código inválido o expirado. Solicita uno nuevo."]
    update_password(user["id"], new_password, must_change=False)
    mark_token_used(email, token)
    return []


# Redefiniciones backend-first para flujo de recuperacion de contrasena.
def request_password_reset(email: str) -> Tuple[Optional[str], str]:
    errs = validate_email(email)
    if errs:
        return None, errs[0]
    try:
        data = _http_post_json(
            "/auth/request-assisted-recovery",
            {"email": email.strip()},
        )
        msg = str((data or {}).get("message", "")).strip() if isinstance(data, dict) else ""
        return None, msg or "Solicitud registrada. Tu recuperación será gestionada por el rol autorizado."
    except ValueError as exc:
        return None, str(exc)
    except requests.RequestException as exc:
        return None, _friendly_backend_error(exc)


def confirm_password_reset(
    email: str, token: str, new_password: str, confirm_password: str
) -> List[str]:
    return [
        "La recuperación directa por código fue deshabilitada. "
        "Debes solicitar recuperación asistida a tu rol autorizado."
    ]


def backend_assisted_reset_password(
    session: UserSession,
    *,
    user_id: int,
) -> Tuple[dict | None, str]:
    try:
        data = _http_request_auth(
            "POST",
            f"/users/{int(user_id)}/assisted-reset-password",
            token=_require_backend_token(session),
        )
        return data if isinstance(data, dict) else None, ""
    except ValueError as exc:
        return None, str(exc)
    except requests.RequestException as exc:
        return None, _friendly_backend_error(exc)


def backend_update_deudor_cliente(
    session: UserSession,
    *,
    rut_original: str,
    empresa: str,
    rut: str,
    nombre: str,
    correo: str = "",
    correo_excel: str = "",
    telefono_fijo: str = "",
    telefono_movil: str = "",
) -> Tuple[dict | None, str]:
    try:
        data = _http_request_auth(
            "PUT",
            f"/deudores/{rut_original}/cliente",
            token=_require_backend_token(session),
            payload={
                "empresa": empresa.strip(),
                "rut": rut.strip(),
                "nombre": nombre.strip(),
                "correo": correo.strip(),
                "correo_excel": correo_excel.strip(),
                "telefono_fijo": telefono_fijo.strip(),
                "telefono_movil": telefono_movil.strip(),
            },
        )
        return data if isinstance(data, dict) else None, ""
    except ValueError as exc:
        return None, str(exc)
    except requests.RequestException as exc:
        return None, _friendly_backend_error(exc)




def backend_get_user_carteras(
    session: UserSession,
    *,
    user_id: int,
) -> Tuple[list[str], str]:
    try:
        if int(user_id) == int(getattr(session, "user_id", 0) or 0):
            path = "/users/me/carteras"
        else:
            path = f"/users/{int(user_id)}/carteras"

        data = _http_request_auth(
            "GET",
            path,
            token=_require_backend_token(session),
        )
        empresas = data.get("empresas", []) if isinstance(data, dict) else []
        empresas_out = empresas if isinstance(empresas, list) else []

        if int(user_id) == int(getattr(session, "user_id", 0) or 0):
            session.empresas_asignadas = empresas_out

        return empresas_out, ""
    except ValueError as exc:
        return [], str(exc)
    except requests.RequestException as exc:
        return [], _friendly_backend_error(exc)


def backend_list_cartera_asignaciones(
    session: UserSession,
) -> Tuple[list[dict], str]:
    try:
        now = time.time()
        cached_at = float(getattr(session, "_cartera_assignments_cache_at", 0.0) or 0.0)
        cached_rows = getattr(session, "_cartera_assignments_cache", None)
        if isinstance(cached_rows, list) and (now - cached_at) <= _CARTERA_ASSIGNMENTS_TTL_SEC:
            return cached_rows, ""

        data = _http_request_auth(
            "GET",
            "/users/carteras",
            token=_require_backend_token(session),
        )
        rows = data if isinstance(data, list) else []
        session._cartera_assignments_cache = rows
        session._cartera_assignments_cache_at = now
        return rows, ""
    except ValueError as exc:
        return [], str(exc)
    except requests.RequestException as exc:
        return [], _friendly_backend_error(exc)


def backend_save_cartera_asignaciones(
    session: UserSession,
    *,
    assignments: list[dict],
) -> Tuple[list[dict], str]:
    try:
        data = _http_request_auth(
            "PUT",
            "/users/carteras",
            token=_require_backend_token(session),
            payload={"assignments": assignments},
        )
        rows = data if isinstance(data, list) else []
        session._cartera_assignments_cache = rows
        session._cartera_assignments_cache_at = time.time()
        return rows, ""
    except ValueError as exc:
        return [], str(exc)
    except requests.RequestException as exc:
        return [], _friendly_backend_error(exc)


def backend_get_legal_acceptance_status(
    session: UserSession,
    *,
    terms_version: str,
    privacy_version: str,
    acceptance_source: str = "desktop_app",
) -> tuple[dict | None, str]:
    try:
        data = _http_request_auth(
            "GET",
            "/auth/legal/acceptance-status",
            token=_require_backend_token(session),
            params={
                "terms_version": str(terms_version or "").strip(),
                "privacy_version": str(privacy_version or "").strip(),
                "acceptance_source": str(acceptance_source or "desktop_app").strip(),
            },
        )
        return data if isinstance(data, dict) else {}, ""
    except ValueError as exc:
        return None, str(exc)
    except requests.RequestException as exc:
        return None, _friendly_backend_error(exc)


def backend_register_legal_acceptance(
    session: UserSession,
    *,
    terms_version: str,
    privacy_version: str,
    acceptance_source: str = "desktop_app",
) -> tuple[dict | None, str]:
    try:
        data = _http_request_auth(
            "POST",
            "/auth/legal/accept",
            token=_require_backend_token(session),
            payload={
                "terms_version": str(terms_version or "").strip(),
                "privacy_version": str(privacy_version or "").strip(),
                "acceptance_source": str(acceptance_source or "desktop_app").strip(),
                "accepted_terms": True,
                "accepted_privacy": True,
            },
        )
        return data if isinstance(data, dict) else {}, ""
    except ValueError as exc:
        return None, str(exc)
    except requests.RequestException as exc:
        return None, _friendly_backend_error(exc)


def backend_list_pending_recovery_requests(
    session: UserSession,
) -> Tuple[list[dict], str]:
    try:
        data = _http_request_auth(
            "GET",
            "/users/assisted-recovery/requests/pending",
            token=_require_backend_token(session),
        )
        return data if isinstance(data, list) else [], ""
    except ValueError as exc:
        return [], str(exc)
    except requests.RequestException as exc:
        return [], _friendly_backend_error(exc)


def backend_reset_pending_recovery_request(
    session: UserSession,
    *,
    request_id: int,
) -> Tuple[dict | None, str]:
    try:
        data = _http_request_auth(
            "POST",
            f"/users/assisted-recovery/requests/{int(request_id)}/reset",
            token=_require_backend_token(session),
        )
        return data if isinstance(data, dict) else None, ""
    except ValueError as exc:
        return None, str(exc)
    except requests.RequestException as exc:
        return None, _friendly_backend_error(exc)


def backend_list_email_templates(
    session: UserSession,
) -> Tuple[list[dict], str]:
    try:
        data = _http_request_auth(
            "GET",
            "/templates/email",
            token=_require_backend_token(session),
        )
        return data if isinstance(data, list) else [], ""
    except ValueError as exc:
        return [], str(exc)
    except requests.RequestException as exc:
        return [], _friendly_backend_error(exc)


def backend_create_email_template(
    session: UserSession,
    *,
    nombre: str,
    asunto: str,
    cuerpo: str,
    is_active: bool = True,
) -> Tuple[dict | None, str]:
    try:
        data = _http_request_auth(
            "POST",
            "/templates/email",
            token=_require_backend_token(session),
            payload={
                "nombre": str(nombre or "").strip(),
                "asunto": str(asunto or "").strip(),
                "cuerpo": str(cuerpo or "").strip(),
                "is_active": bool(is_active),
            },
        )
        return data if isinstance(data, dict) else None, ""
    except ValueError as exc:
        return None, str(exc)
    except requests.RequestException as exc:
        return None, _friendly_backend_error(exc)


def backend_update_email_template(
    session: UserSession,
    *,
    template_id: int,
    nombre: str,
    asunto: str,
    cuerpo: str,
    is_active: bool = True,
) -> Tuple[dict | None, str]:
    try:
        data = _http_request_auth(
            "PUT",
            f"/templates/email/{int(template_id)}",
            token=_require_backend_token(session),
            payload={
                "nombre": str(nombre or "").strip(),
                "asunto": str(asunto or "").strip(),
                "cuerpo": str(cuerpo or "").strip(),
                "is_active": bool(is_active),
            },
        )
        return data if isinstance(data, dict) else None, ""
    except ValueError as exc:
        return None, str(exc)
    except requests.RequestException as exc:
        return None, _friendly_backend_error(exc)


def backend_delete_email_template(
    session: UserSession,
    *,
    template_id: int,
) -> str:
    try:
        _http_request_auth(
            "DELETE",
            f"/templates/email/{int(template_id)}",
            token=_require_backend_token(session),
        )
        return ""
    except ValueError as exc:
        return str(exc)
    except requests.RequestException as exc:
        return _friendly_backend_error(exc)


def backend_close_session(session: UserSession) -> str:
    if getattr(session, "auth_source", "") != "backend":
        return ""
    try:
        _http_request_auth(
            "POST",
            "/auth/logout",
            token=_require_backend_token(session),
            payload={"session_history_id": getattr(session, "session_history_id", None)},
        )
        return ""
    except ValueError as exc:
        return str(exc)
    except requests.RequestException as exc:
        return _friendly_backend_error(exc)


