"""Búsqueda, descarga y lanzamiento de actualizaciones publicadas en GitHub Releases.

No depende de Qt para poder probarse sin entorno gráfico.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

from core.version import APP_VERSION, UPDATE_REPO

logger = logging.getLogger(__name__)

API_URL = "https://api.github.com/repos/{repo}/releases/latest"
SETUP_NAME_RE = re.compile(r"^ControliaCobranzas_Setup_[0-9.]+\.exe$", re.IGNORECASE)
CHECKSUMS_NAME = "SHA256SUMS.txt"
REQUEST_TIMEOUT = 10
CHUNK_SIZE = 256 * 1024

# Inno Setup: actualiza sobre la instalación existente sin mostrar el asistente.
# La app se reabre desde la entrada [Run] del .iss.
INSTALLER_ARGS = "/SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS"


class UpdateError(Exception):
    """Error que se puede mostrar tal cual al usuario."""


class UpdateCancelled(UpdateError):
    pass


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    setup_name: str
    setup_url: str
    setup_size: int
    checksums_url: str
    notes: str


def parse_version(text: str) -> tuple[int, ...]:
    cleaned = str(text or "").strip().lstrip("vV")
    parts = cleaned.split(".")
    if not cleaned or not all(p.isdigit() for p in parts):
        raise ValueError(f"Versión inválida: {text!r}")
    return tuple(int(p) for p in parts)


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    try:
        r, l = parse_version(remote), parse_version(local)
    except ValueError:
        return False
    # Rellena con ceros para que 2.5 == 2.5.0.
    size = max(len(r), len(l))
    return r + (0,) * (size - len(r)) > l + (0,) * (size - len(l))


def parse_release(payload: dict) -> ReleaseInfo | None:
    if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
        return None
    try:
        version = ".".join(str(n) for n in parse_version(payload.get("tag_name", "")))
    except ValueError:
        return None

    setup = checksums = None
    for asset in payload.get("assets") or []:
        name = str(asset.get("name", ""))
        if SETUP_NAME_RE.match(name):
            setup = asset
        elif name == CHECKSUMS_NAME:
            checksums = asset
    if not setup or not checksums:
        return None

    return ReleaseInfo(
        version=version,
        setup_name=str(setup["name"]),
        setup_url=str(setup["browser_download_url"]),
        setup_size=int(setup.get("size") or 0),
        checksums_url=str(checksums["browser_download_url"]),
        notes=str(payload.get("body") or "").strip(),
    )


def _headers() -> dict[str, str]:
    return {"User-Agent": f"ControliaCobranzas/{APP_VERSION}"}


def check_latest(repo: str = UPDATE_REPO) -> ReleaseInfo | None:
    resp = requests.get(
        API_URL.format(repo=repo),
        headers={**_headers(), "Accept": "application/vnd.github+json"},
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code == 404:
        return None  # Repositorio sin releases publicadas.
    resp.raise_for_status()
    return parse_release(resp.json())


def find_update(repo: str = UPDATE_REPO) -> ReleaseInfo | None:
    release = check_latest(repo)
    if release and is_newer(release.version):
        return release
    return None


def expected_sha256(checksums_text: str, filename: str) -> str:
    # Formato de sha256sum: "<hash>  <archivo>" o "<hash> *<archivo>".
    for line in checksums_text.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and parts[1].lstrip("*").strip() == filename:
            digest = parts[0].lower()
            if re.fullmatch(r"[0-9a-f]{64}", digest):
                return digest
    raise UpdateError(f"La release no publica el hash SHA256 de {filename}.")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def get_updates_dir() -> Path:
    path = Path(tempfile.gettempdir()) / "ControliaCobranzas_updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def download_update(
    release: ReleaseInfo,
    progress_cb: Callable[[int, int], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    dest_dir: Path | None = None,
) -> Path:
    dest_dir = dest_dir or get_updates_dir()
    dest = dest_dir / release.setup_name
    part = dest.with_name(dest.name + ".part")

    try:
        resp = requests.get(release.checksums_url, headers=_headers(), timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise UpdateError(f"No se pudo descargar la verificación de la actualización: {exc}") from exc
    expected = expected_sha256(resp.text, release.setup_name)

    if dest.exists() and sha256_of(dest) == expected:
        return dest

    try:
        with requests.get(
            release.setup_url, headers=_headers(), timeout=REQUEST_TIMEOUT, stream=True
        ) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length") or release.setup_size or 0)
            done = 0
            with open(part, "wb") as fh:
                for chunk in resp.iter_content(CHUNK_SIZE):
                    if is_cancelled and is_cancelled():
                        raise UpdateCancelled("Descarga cancelada.")
                    fh.write(chunk)
                    done += len(chunk)
                    if progress_cb:
                        progress_cb(done, total)
    except requests.RequestException as exc:
        part.unlink(missing_ok=True)
        raise UpdateError(f"No se pudo descargar la actualización: {exc}") from exc
    except UpdateError:
        part.unlink(missing_ok=True)
        raise

    if sha256_of(part) != expected:
        part.unlink(missing_ok=True)
        raise UpdateError("El archivo descargado no coincide con el publicado. Se descartó por seguridad.")

    os.replace(part, dest)
    return dest


def can_self_update() -> bool:
    """Solo el ejecutable instalado puede reemplazarse a sí mismo."""
    return bool(getattr(sys, "frozen", False)) and sys.platform == "win32"


def launch_installer(path: Path) -> None:
    if not can_self_update():
        raise UpdateError("La actualización automática solo funciona en la aplicación instalada.")
    logger.info("Lanzando instalador de actualización: %s", path)
    # ShellExecute (os.startfile) deja que Windows pida UAC si el setup lo requiere.
    os.startfile(str(path), "open", INSTALLER_ARGS)
