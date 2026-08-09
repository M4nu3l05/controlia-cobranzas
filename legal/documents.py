from __future__ import annotations

import re
import shutil
from pathlib import Path

from core.paths import get_config_dir
from core.runtime import resource_path

from .constants import (
    LEGAL_DIRNAME,
    PRIVACY_FILENAME,
    PRIVACY_VERSION,
    TERMS_FILENAME,
    TERMS_VERSION,
)


def _decode_text(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def _packaged_paths(filename: str) -> list[Path]:
    return [
        Path(resource_path(str(Path(LEGAL_DIRNAME) / filename))),
        Path(__file__).resolve().parents[1] / LEGAL_DIRNAME / filename,
        Path.cwd() / LEGAL_DIRNAME / filename,
    ]


def _candidate_paths(filename: str) -> list[Path]:
    config_path = Path(get_config_dir()) / LEGAL_DIRNAME / filename
    return [config_path, *_packaged_paths(filename)]


def resolve_legal_file(filename: str) -> Path | None:
    for path in _candidate_paths(filename):
        if path.exists() and path.is_file():
            return path
    return None


def _document_version(text: str) -> str:
    match = re.search(r"Versión del documento:\s*([^\s]+)", text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _expected_version(filename: str) -> str:
    if filename == TERMS_FILENAME:
        return TERMS_VERSION
    if filename == PRIVACY_FILENAME:
        return PRIVACY_VERSION
    return ""


def _ensure_config_copy(filename: str) -> None:
    cfg_dir = Path(get_config_dir()) / LEGAL_DIRNAME
    cfg_dir.mkdir(parents=True, exist_ok=True)
    target = cfg_dir / filename

    expected_version = _expected_version(filename)
    if target.exists() and expected_version:
        try:
            current_text = _decode_text(target.read_bytes())
            if _document_version(current_text) == expected_version:
                return
        except Exception:
            pass

    source = next((path for path in _packaged_paths(filename) if path.exists() and path.is_file()), None)
    if source:
        try:
            shutil.copy2(source, target)
        except Exception:
            pass


def get_terms_text() -> tuple[str, str]:
    return get_legal_text(TERMS_FILENAME, "Términos y Condiciones")


def get_privacy_text() -> tuple[str, str]:
    return get_legal_text(PRIVACY_FILENAME, "Política de Privacidad")


def get_legal_text(filename: str, label: str) -> tuple[str, str]:
    _ensure_config_copy(filename)
    path = resolve_legal_file(filename)
    if not path:
        return "", f"No se encontró el archivo de {label}: {filename}."

    try:
        raw = path.read_bytes()
        text = _decode_text(raw).strip()
        if not text:
            return "", f"El archivo {filename} está vacío."
        return text, ""
    except Exception as exc:
        return "", f"No fue posible leer {filename}: {exc}"


def ensure_legal_documents_available() -> None:
    _ensure_config_copy(TERMS_FILENAME)
    _ensure_config_copy(PRIVACY_FILENAME)
