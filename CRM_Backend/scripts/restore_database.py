from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from db_tools import (
    postgres_cli_args,
    postgres_environment,
    postgres_url,
    require_program,
    verify_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Restaura un respaldo de Controlia CRM de forma controlada.")
    parser.add_argument("backup", help="Archivo .backup generado por backup_database.py")
    parser.add_argument("--database-url", default=os.getenv("STAGING_DATABASE_URL", ""))
    parser.add_argument("--confirm-database", required=True, help="Nombre exacto de la base de destino.")
    parser.add_argument("--allow-production", action="store_true")
    args = parser.parse_args()

    backup = Path(args.backup).expanduser().resolve()
    if not backup.is_file():
        raise ValueError(f"No existe el respaldo: {backup}")
    verify_manifest(backup)

    url = postgres_url(args.database_url)
    if args.confirm_database != url.database:
        raise ValueError("La confirmación no coincide con la base de destino; restauración cancelada.")
    app_env = os.getenv("APP_ENV", "staging").strip().lower()
    if app_env == "production" and not args.allow_production:
        raise ValueError("Restauración productiva bloqueada. Usa un entorno de ensayo independiente.")

    pg_restore = require_program("pg_restore")
    command = [
        pg_restore,
        *postgres_cli_args(url),
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-acl",
        "--single-transaction",
        str(backup),
    ]
    subprocess.run(command, env=postgres_environment(url), check=True)
    print(f"Restauración completada en la base de ensayo: {url.database}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
