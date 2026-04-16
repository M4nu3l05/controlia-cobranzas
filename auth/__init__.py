"""
Paquete auth — autenticación y roles para Controlia Cobranzas.

  auth_db       → SQLite + PBKDF2 + roles
  auth_service  → lógica de negocio
  views/        → UI PyQt6
"""
from .auth_db import ensure_default_admin, ROLES, ROLE_ADMIN, ROLE_SUPERVISOR, ROLE_EJECUTIVO
from .auth_service import UserSession
from .views.auth_window import AuthWindow

__all__ = [
    "AuthWindow", "UserSession", "ensure_default_admin",
    "ROLES", "ROLE_ADMIN", "ROLE_SUPERVISOR", "ROLE_EJECUTIVO",
]