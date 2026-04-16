from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable, Iterable


@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    apply: Callable[[sqlite3.Connection], None]


def ensure_migrations_table(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.commit()


def current_version(con: sqlite3.Connection) -> int:
    ensure_migrations_table(con)
    row = con.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    return int(row[0] or 0)


def apply_migrations(con: sqlite3.Connection, migrations: Iterable[Migration]) -> int:
    ensure_migrations_table(con)
    applied = 0
    current = current_version(con)
    ordered = sorted(migrations, key=lambda m: m.version)
    for migration in ordered:
        if migration.version <= current:
            continue
        migration.apply(con)
        con.execute(
            "INSERT INTO schema_migrations(version, description) VALUES (?, ?)",
            (migration.version, migration.description),
        )
        con.commit()
        applied += 1
        current = migration.version
    return applied
