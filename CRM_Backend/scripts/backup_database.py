from __future__ import annotations

import argparse
import os
import subprocess
from datetime import datetime
from pathlib import Path

from db_tools import (
    postgres_cli_args,
    postgres_environment,
    postgres_url,
    require_program,
    write_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera un respaldo verificable de Controlia CRM.")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument("--output-dir", required=True, help="Carpeta externa donde guardar el respaldo.")
    args = parser.parse_args()

    url = postgres_url(args.database_url)
    pg_dump = require_program("pg_dump")
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = output_dir / f"controlia_{url.database}_{timestamp}.backup"
    partial = destination.with_suffix(destination.suffix + ".partial")

    command = [
        pg_dump,
        *postgres_cli_args(url),
        "--format=custom",
        "--no-owner",
        "--no-acl",
        "--file",
        str(partial),
    ]
    try:
        subprocess.run(command, env=postgres_environment(url), check=True)
        partial.replace(destination)
        manifest = write_manifest(destination, url)
    finally:
        if partial.exists():
            partial.unlink()

    print(f"Respaldo creado: {destination}")
    print(f"Manifiesto: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
