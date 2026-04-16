# ================================================================
#  envios/config.py
#  Configuración SMTP persistente + sesión SMTP en memoria.
# ================================================================

from __future__ import annotations

import json
import logging
from pathlib import Path

from core.paths import get_config_dir

logger = logging.getLogger(__name__)

SMTP_PRESETS = {
    "Outlook / Hotmail": {"host": "smtp-mail.outlook.com", "port": 587, "tls": True},
    "Gmail": {"host": "smtp.gmail.com", "port": 587, "tls": True},
    "Yahoo": {"host": "smtp.mail.yahoo.com", "port": 587, "tls": True},
    "Personalizado": {"host": "", "port": 587, "tls": True},
}

CONFIG_KEYS = ["preset", "host", "port", "tls", "usuario", "nombre_remitente"]
_CONFIG_FILE: str | None = None

# Sesión SMTP viva solo en memoria mientras la app está abierta
_SMTP_SESSION: dict = {}


def _config_path() -> str:
    global _CONFIG_FILE
    if _CONFIG_FILE:
        return _CONFIG_FILE
    path = Path(get_config_dir()) / "smtp_config.json"
    _CONFIG_FILE = str(path)
    return _CONFIG_FILE


def guardar_config(cfg: dict) -> None:
    """Persiste la configuración SMTP sin almacenar la contraseña."""
    data = {k: cfg.get(k) for k in CONFIG_KEYS if k in cfg}
    with open(_config_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def cargar_config() -> dict:
    path = _config_path()
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        logger.exception("No se pudo cargar la configuración SMTP")
        return {}


def config_completa(cfg: dict) -> bool:
    required = ("host", "usuario", "password")
    for key in required:
        val = cfg.get(key, "")
        if not str(val).strip():
            return False
    return True


# ────────────────────────────────────────────────────────────────
#  Sesión SMTP compartida en memoria
# ────────────────────────────────────────────────────────────────

def guardar_sesion_smtp(cfg: dict) -> None:
    """
    Guarda la sesión SMTP activa solo en memoria.
    Debe incluir al menos:
      host, port, tls, usuario, password, nombre_remitente
    """
    global _SMTP_SESSION
    _SMTP_SESSION = {
        "host": str(cfg.get("host", "")).strip(),
        "port": int(cfg.get("port", 587) or 587),
        "tls": bool(cfg.get("tls", True)),
        "usuario": str(cfg.get("usuario", "")).strip(),
        "password": str(cfg.get("password", "")).strip(),
        "nombre_remitente": str(cfg.get("nombre_remitente", "")).strip() or str(cfg.get("usuario", "")).strip(),
    }


def cargar_sesion_smtp() -> dict:
    return dict(_SMTP_SESSION)


def limpiar_sesion_smtp() -> None:
    global _SMTP_SESSION
    _SMTP_SESSION = {}


def sesion_smtp_activa() -> bool:
    if not _SMTP_SESSION:
        return False
    required = ("host", "usuario", "password")
    for key in required:
        val = _SMTP_SESSION.get(key, "")
        if not str(val).strip():
            return False
    return True