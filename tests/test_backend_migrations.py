import sys
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "CRM_Backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.db.migrations import MIGRATIONS, applied_versions, apply_backend_migrations


def test_backend_migrations_are_versioned_and_idempotent():
    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as db:
        first = apply_backend_migrations(db)
        second = apply_backend_migrations(db)
        versions = applied_versions(db)

    expected = {migration.version for migration in MIGRATIONS}
    assert first == sorted(expected)
    assert second == []
    assert versions == expected

    tables = set(inspect(engine).get_table_names())
    assert "payment_transactions" in tables
    assert "customer_change_audit" in tables
    assert "debtor_import_batches" in tables
    assert "backend_schema_migrations" in tables
