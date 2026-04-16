from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from core.db_migrations import Migration, apply_migrations
from core.paths import get_data_dir

from .constants import ACCEPTANCE_SOURCE_DESKTOP


@dataclass
class LegalAcceptanceStatus:
    user_id: int
    has_valid_acceptance: bool
    accepted_terms: bool
    accepted_privacy: bool
    terms_version: str
    privacy_version: str
    accepted_at: str
    acceptance_source: str


def _db_path() -> str:
    return os.path.join(str(get_data_dir()), "db_legal.sqlite")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _m1_create_legal_tables(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS legal_acceptance_current (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            user_email TEXT NOT NULL DEFAULT '',
            username TEXT NOT NULL DEFAULT '',
            accepted_terms INTEGER NOT NULL DEFAULT 0,
            accepted_privacy INTEGER NOT NULL DEFAULT 0,
            terms_version TEXT NOT NULL,
            privacy_version TEXT NOT NULL,
            accepted_at TEXT NOT NULL,
            acceptance_source TEXT NOT NULL DEFAULT 'desktop_app',
            client_version TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, acceptance_source)
        )
        """
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_legal_current_user_source ON legal_acceptance_current(user_id, acceptance_source)"
    )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS legal_acceptance_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            user_email TEXT NOT NULL DEFAULT '',
            username TEXT NOT NULL DEFAULT '',
            accepted_terms INTEGER NOT NULL DEFAULT 0,
            accepted_privacy INTEGER NOT NULL DEFAULT 0,
            terms_version TEXT NOT NULL,
            privacy_version TEXT NOT NULL,
            accepted_at TEXT NOT NULL,
            acceptance_source TEXT NOT NULL DEFAULT 'desktop_app',
            client_version TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_legal_events_user_source ON legal_acceptance_events(user_id, acceptance_source)"
    )


MIGRATIONS = [
    Migration(1, "Create legal acceptance tables", _m1_create_legal_tables),
]


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    apply_migrations(con, MIGRATIONS)
    return con


def _to_bool(value) -> bool:
    return bool(int(value or 0))


def get_status(
    *,
    user_id: int,
    terms_version: str,
    privacy_version: str,
    acceptance_source: str = ACCEPTANCE_SOURCE_DESKTOP,
) -> LegalAcceptanceStatus:
    with _con() as con:
        row = con.execute(
            """
            SELECT *
            FROM legal_acceptance_current
            WHERE user_id = ? AND acceptance_source = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (int(user_id), str(acceptance_source or ACCEPTANCE_SOURCE_DESKTOP).strip()),
        ).fetchone()

    if not row:
        return LegalAcceptanceStatus(
            user_id=int(user_id),
            has_valid_acceptance=False,
            accepted_terms=False,
            accepted_privacy=False,
            terms_version="",
            privacy_version="",
            accepted_at="",
            acceptance_source=str(acceptance_source or ACCEPTANCE_SOURCE_DESKTOP),
        )

    accepted_terms = _to_bool(row["accepted_terms"])
    accepted_privacy = _to_bool(row["accepted_privacy"])
    current_terms = str(row["terms_version"] or "")
    current_privacy = str(row["privacy_version"] or "")
    valid = (
        accepted_terms
        and accepted_privacy
        and current_terms == str(terms_version or "")
        and current_privacy == str(privacy_version or "")
    )

    return LegalAcceptanceStatus(
        user_id=int(user_id),
        has_valid_acceptance=bool(valid),
        accepted_terms=accepted_terms,
        accepted_privacy=accepted_privacy,
        terms_version=current_terms,
        privacy_version=current_privacy,
        accepted_at=str(row["accepted_at"] or ""),
        acceptance_source=str(row["acceptance_source"] or ""),
    )


def register_acceptance(
    *,
    user_id: int,
    user_email: str,
    username: str,
    terms_version: str,
    privacy_version: str,
    acceptance_source: str = ACCEPTANCE_SOURCE_DESKTOP,
    client_version: str = "",
) -> LegalAcceptanceStatus:
    now = _utc_now_iso()
    source = str(acceptance_source or ACCEPTANCE_SOURCE_DESKTOP).strip() or ACCEPTANCE_SOURCE_DESKTOP

    payload = (
        int(user_id),
        str(user_email or "").strip(),
        str(username or "").strip(),
        1,
        1,
        str(terms_version or "").strip(),
        str(privacy_version or "").strip(),
        now,
        source,
        str(client_version or "").strip(),
    )

    with _con() as con:
        con.execute(
            """
            INSERT INTO legal_acceptance_events (
                user_id, user_email, username,
                accepted_terms, accepted_privacy,
                terms_version, privacy_version,
                accepted_at, acceptance_source, client_version,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload + (now,),
        )

        existing = con.execute(
            """
            SELECT id FROM legal_acceptance_current
            WHERE user_id = ? AND acceptance_source = ?
            LIMIT 1
            """,
            (int(user_id), source),
        ).fetchone()

        if existing:
            con.execute(
                """
                UPDATE legal_acceptance_current
                SET user_email = ?,
                    username = ?,
                    accepted_terms = 1,
                    accepted_privacy = 1,
                    terms_version = ?,
                    privacy_version = ?,
                    accepted_at = ?,
                    client_version = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    str(user_email or "").strip(),
                    str(username or "").strip(),
                    str(terms_version or "").strip(),
                    str(privacy_version or "").strip(),
                    now,
                    str(client_version or "").strip(),
                    now,
                    int(existing["id"]),
                ),
            )
        else:
            con.execute(
                """
                INSERT INTO legal_acceptance_current (
                    user_id, user_email, username,
                    accepted_terms, accepted_privacy,
                    terms_version, privacy_version,
                    accepted_at, acceptance_source, client_version,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload + (now, now),
            )

        con.commit()

    return get_status(
        user_id=int(user_id),
        terms_version=str(terms_version or ""),
        privacy_version=str(privacy_version or ""),
        acceptance_source=source,
    )
