# ================================================================
#  auth/auth_db.py
#
#  Base de datos de autenticacion — PBKDF2-HMAC-SHA256
#  Tablas : users, reset_tokens
#  Roles  : admin | supervisor | ejecutivo
# ================================================================

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

from core.db_migrations import Migration, apply_migrations
from core.paths import get_data_dir

logger = logging.getLogger(__name__)

_ITERATIONS   = 480_000
_HASH_ALGO    = "sha256"
_SALT_BYTES   = 32
_RESET_EXPIRY = 15

ROLES = {
    "admin":      "Administrador",
    "supervisor": "Supervisor",
    "ejecutivo":  "Ejecutivo",
}
ROLE_ADMIN      = "admin"
ROLE_SUPERVISOR = "supervisor"
ROLE_EJECUTIVO  = "ejecutivo"


@dataclass
class UserSession:
    user_id:              int
    email:                str
    username:             str
    role:                 str
    is_active:            bool
    must_change_password: bool

    @classmethod
    def from_db(cls, row: dict) -> "UserSession":
        return cls(
            user_id=row["id"],
            email=row["email"],
            username=row["username"],
            role=row.get("role", ROLE_EJECUTIVO),
            is_active=bool(row["is_active"]),
            must_change_password=bool(row.get("must_change_password", 0)),
        )

    @property
    def role_label(self) -> str:
        return ROLES.get(self.role, self.role.capitalize())

    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    def is_supervisor_or_above(self) -> bool:
        return self.role in (ROLE_ADMIN, ROLE_SUPERVISOR)

    def is_ejecutivo(self) -> bool:
        return self.role == ROLE_EJECUTIVO


def _db_path() -> str:
    return os.path.join(str(get_data_dir()), "db_auth.sqlite")


def _m1_create_users(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            email                TEXT    NOT NULL UNIQUE,
            username             TEXT    NOT NULL,
            password_hash        TEXT    NOT NULL,
            salt                 TEXT    NOT NULL,
            role                 TEXT    NOT NULL DEFAULT 'ejecutivo',
            is_active            INTEGER NOT NULL DEFAULT 1,
            must_change_password INTEGER NOT NULL DEFAULT 0,
            created_at           TEXT    NOT NULL,
            updated_at           TEXT    NOT NULL
        )
    """)
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)")


def _m2_create_reset_tokens(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS reset_tokens (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            token      TEXT    NOT NULL UNIQUE,
            expires_at TEXT    NOT NULL,
            used       INTEGER NOT NULL DEFAULT 0,
            created_at TEXT    NOT NULL
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_reset_user ON reset_tokens(user_id)")


def _m3_add_role_and_mcp(con: sqlite3.Connection) -> None:
    for col, defn in [
        ("role",                 "TEXT NOT NULL DEFAULT 'ejecutivo'"),
        ("must_change_password", "INTEGER NOT NULL DEFAULT 0"),
    ]:
        try:
            con.execute(f"ALTER TABLE users ADD COLUMN {col} {defn}")
        except sqlite3.OperationalError:
            pass


MIGRATIONS = [
    Migration(1, "Create users table",          _m1_create_users),
    Migration(2, "Create reset_tokens table",   _m2_create_reset_tokens),
    Migration(3, "Add role and must_change_pw", _m3_add_role_and_mcp),
]


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    apply_migrations(con, MIGRATIONS)
    return con


def _gen_salt() -> str:
    return secrets.token_hex(_SALT_BYTES)


def hash_password(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac(
        _HASH_ALGO,
        password.encode("utf-8"),
        salt.encode("utf-8"),
        _ITERATIONS,
    )
    return dk.hex()


def verify_password(password: str, salt: str, stored_hash: str) -> bool:
    return secrets.compare_digest(hash_password(password, salt), stored_hash)


def create_user(
    email: str,
    username: str,
    password: str,
    role: str = ROLE_EJECUTIVO,
    must_change_password: bool = False,
) -> dict:
    if role not in ROLES:
        raise ValueError(f"Rol no valido: '{role}'. Usa: {', '.join(ROLES)}")
    email_norm = email.strip().lower()
    now  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    salt = _gen_salt()
    ph   = hash_password(password, salt)
    mcp  = 1 if must_change_password else 0
    with _con() as con:
        try:
            con.execute(
                "INSERT INTO users(email,username,password_hash,salt,role,"
                "is_active,must_change_password,created_at,updated_at)"
                " VALUES(?,?,?,?,?,1,?,?,?)",
                (email_norm, username.strip(), ph, salt, role, mcp, now, now),
            )
            con.commit()
        except sqlite3.IntegrityError:
            raise ValueError(f"El correo '{email_norm}' ya esta registrado.")
        row = con.execute("SELECT * FROM users WHERE email=?", (email_norm,)).fetchone()
        return dict(row)


def get_user_by_email(email: str) -> Optional[dict]:
    with _con() as con:
        row = con.execute(
            "SELECT * FROM users WHERE email=?", (email.strip().lower(),)
        ).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[dict]:
    with _con() as con:
        row = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_all_users() -> List[dict]:
    with _con() as con:
        rows = con.execute(
            "SELECT id,email,username,role,is_active,must_change_password,"
            "created_at,updated_at FROM users ORDER BY role,username"
        ).fetchall()
        return [dict(r) for r in rows]


def update_password(user_id: int, new_password: str, must_change: bool = False) -> None:
    salt = _gen_salt()
    ph   = hash_password(new_password, salt)
    now  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _con() as con:
        con.execute(
            "UPDATE users SET password_hash=?,salt=?,must_change_password=?,"
            "updated_at=? WHERE id=?",
            (ph, salt, 1 if must_change else 0, now, user_id),
        )
        con.commit()


def update_user(user_id: int, username: str = None,
                role: str = None, is_active: bool = None) -> None:
    fields, vals = [], []
    if username  is not None:
        fields.append("username=?")
        vals.append(username.strip())
    if role is not None:
        if role not in ROLES:
            raise ValueError(f"Rol no valido: '{role}'")
        fields.append("role=?")
        vals.append(role)
    if is_active is not None:
        fields.append("is_active=?")
        vals.append(1 if is_active else 0)
    if not fields:
        return
    fields.append("updated_at=?")
    vals.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    vals.append(user_id)
    with _con() as con:
        con.execute(f"UPDATE users SET {', '.join(fields)} WHERE id=?", vals)
        con.commit()


def email_exists(email: str) -> bool:
    return get_user_by_email(email) is not None


def count_admin_users(active_only: bool = False) -> int:
    sql = "SELECT COUNT(*) FROM users WHERE role=?"
    params = [ROLE_ADMIN]
    if active_only:
        sql += " AND is_active=1"
    with _con() as con:
        row = con.execute(sql, params).fetchone()
        return int(row[0] if row else 0)


def delete_user(user_id: int) -> None:
    user = get_user_by_id(user_id)
    if not user:
        raise ValueError("El usuario no existe o ya fue eliminado.")

    if str(user.get("role", "")) == ROLE_ADMIN and count_admin_users(active_only=False) <= 1:
        raise ValueError("No puedes eliminar el último administrador del sistema.")

    with _con() as con:
        con.execute("DELETE FROM reset_tokens WHERE user_id=?", (user_id,))
        cur = con.execute("DELETE FROM users WHERE id=?", (user_id,))
        con.commit()

        if cur.rowcount == 0:
            raise ValueError("No se pudo eliminar el usuario.")


def create_reset_token(user_id: int) -> str:
    with _con() as con:
        con.execute("UPDATE reset_tokens SET used=1 WHERE user_id=?", (user_id,))
        token   = str(secrets.randbelow(900_000) + 100_000)
        expires = (datetime.now() + timedelta(minutes=_RESET_EXPIRY)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        con.execute(
            "INSERT INTO reset_tokens(user_id,token,expires_at,used,created_at)"
            " VALUES(?,?,?,0,?)",
            (user_id, token, expires, now),
        )
        con.commit()
    return token


def validate_reset_token(email: str, token: str) -> Optional[dict]:
    user = get_user_by_email(email)
    if not user:
        return None
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _con() as con:
        row = con.execute(
            "SELECT id FROM reset_tokens"
            " WHERE user_id=? AND token=? AND used=0 AND expires_at>?",
            (user["id"], token.strip(), now),
        ).fetchone()
    return user if row else None


def mark_token_used(email: str, token: str) -> None:
    user = get_user_by_email(email)
    if not user:
        return
    with _con() as con:
        con.execute(
            "UPDATE reset_tokens SET used=1 WHERE user_id=? AND token=?",
            (user["id"], token.strip()),
        )
        con.commit()


# ── Bootstrap seguro ──────────────────────────────────────────
def ensure_default_admin() -> None:
    """
    Crea el admin inicial SOLO si no hay ningun usuario.

    Seguridad implementada:
      1. Contrasena temporal en archivo local (no en consola ni logs).
      2. must_change_password=True: obliga cambio en el primer login.
      3. Email configurable via variable de entorno CONTROLIA_COBRANZAS_ADMIN_EMAIL.
      4. El archivo de credenciales se elimina tras el primer cambio.
    """
    with _con() as con:
        count = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count > 0:
        return

    admin_email = os.environ.get("CONTROLIA_COBRANZAS_ADMIN_EMAIL", "admin@controlia.cl")
    temp_pw     = secrets.token_urlsafe(14)

    create_user(
        email=admin_email,
        username="Administrador",
        password=temp_pw,
        role=ROLE_ADMIN,
        must_change_password=True,
    )

    cred_path = os.path.join(str(get_data_dir()), "setup_credentials.txt")
    try:
        with open(cred_path, "w", encoding="utf-8") as f:
            f.write(
                "=" * 58 + "\n"
                "  Controlia Cobranzas — Credenciales del primer inicio\n"
                "=" * 58 + "\n"
                f"  Email      : {admin_email}\n"
                f"  Contrasena : {temp_pw}\n"
                "=" * 58 + "\n"
                "  IMPORTANTE:\n"
                "  * Inicia sesion con estas credenciales.\n"
                "  * El sistema te pedira crear una nueva contrasena.\n"
                "  * Este archivo se eliminara automaticamente.\n"
                "=" * 58 + "\n"
            )
        print(f"\n  [Controlia Cobranzas] Primer inicio detectado.")
        print(f"  Credenciales en: {cred_path}\n")
        logger.info("Primer inicio: credenciales en %s", cred_path)
    except OSError as exc:
        logger.error("No se pudo escribir setup_credentials.txt: %s", exc)
        print(f"\n  [Controlia Cobranzas] ATENCION: no se pudo crear el archivo de credenciales.")
        print(f"  Email: {admin_email}  |  Contrasena temporal: {temp_pw}")
        print(f"  Cambia la contrasena inmediatamente.\n")


def delete_setup_credentials_file() -> None:
    cred_path = os.path.join(str(get_data_dir()), "setup_credentials.txt")
    try:
        if os.path.exists(cred_path):
            os.remove(cred_path)
    except OSError as exc:
        logger.warning("No se pudo eliminar setup_credentials.txt: %s", exc)