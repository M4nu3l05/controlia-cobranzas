from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import URL, make_url


def postgres_url(raw_url: str) -> URL:
    if not raw_url:
        raise ValueError("Falta la URL de conexión PostgreSQL.")
    url = make_url(raw_url)
    if not url.drivername.startswith("postgresql"):
        raise ValueError("La operación solo admite bases PostgreSQL.")
    if not url.database:
        raise ValueError("La URL no contiene el nombre de la base de datos.")
    return url


def require_program(name: str) -> str:
    executable = shutil.which(name)
    if not executable and os.name == "nt":
        postgres_root = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "PostgreSQL"
        candidates = sorted(
            postgres_root.glob(f"*/bin/{name}.exe"),
            key=lambda path: path.parts[-3],
            reverse=True,
        )
        executable = str(candidates[0]) if candidates else None
    if not executable:
        raise RuntimeError(
            f"No se encontró '{name}'. Instala las herramientas cliente de PostgreSQL y vuelve a intentar."
        )
    return executable


def postgres_cli_args(url: URL) -> list[str]:
    args: list[str] = []
    if url.host:
        args.extend(["--host", url.host])
    if url.port:
        args.extend(["--port", str(url.port)])
    if url.username:
        args.extend(["--username", url.username])
    args.extend(["--dbname", str(url.database)])
    return args


def postgres_environment(url: URL) -> dict[str, str]:
    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = url.password
    return env


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(backup_path: Path, url: URL) -> Path:
    manifest_path = backup_path.with_suffix(backup_path.suffix + ".json")
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "database": str(url.database),
        "host": url.host or "localhost",
        "format": "postgresql-custom",
        "filename": backup_path.name,
        "size_bytes": backup_path.stat().st_size,
        "sha256": sha256_file(backup_path),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def verify_manifest(backup_path: Path) -> None:
    manifest_path = backup_path.with_suffix(backup_path.suffix + ".json")
    if not manifest_path.exists():
        raise ValueError(f"Falta el manifiesto de integridad: {manifest_path.name}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = str(manifest.get("sha256", ""))
    actual = sha256_file(backup_path)
    if not expected or expected != actual:
        raise ValueError("El respaldo no supera la verificación SHA-256; no es seguro restaurarlo.")
