import sys
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

SCRIPTS_ROOT = Path(__file__).resolve().parents[1] / "CRM_Backend" / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from db_tools import postgres_cli_args, postgres_url, verify_manifest, write_manifest


def test_backup_manifest_detects_tampering(tmp_path):
    backup = tmp_path / "controlia_test.backup"
    backup.write_bytes(b"respaldo-ficticio")
    url = postgres_url("postgresql+psycopg2://user:secret@localhost:5432/controlia_test")
    write_manifest(backup, url)
    verify_manifest(backup)

    backup.write_bytes(b"contenido-alterado")
    with pytest.raises(ValueError, match="SHA-256"):
        verify_manifest(backup)


def test_cli_arguments_never_include_password():
    url = postgres_url("postgresql://user:very-secret@db.example.test:5432/controlia")
    args = postgres_cli_args(url)
    assert "very-secret" not in " ".join(args)
    assert "controlia" in args


def test_non_postgresql_database_is_rejected():
    with pytest.raises(ValueError, match="PostgreSQL"):
        postgres_url("sqlite:///controlia.db")
