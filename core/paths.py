from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Controlia Cobranzas"


def _is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _base_dir() -> Path:
    appdata = os.getenv("APPDATA")
    candidates: list[Path] = []
    if appdata:
        candidates.append(Path(appdata) / APP_NAME)
    candidates.append(Path.home() / f".{APP_NAME.lower()}")
    candidates.append(Path.cwd() / ".runtime" / APP_NAME)

    for candidate in candidates:
        if _is_writable_dir(candidate):
            return candidate

    # Last resort: return the first candidate and let caller raise if needed.
    return candidates[0]


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_app_dir() -> Path:
    return ensure_dir(_base_dir())


def get_data_dir() -> Path:
    return ensure_dir(get_app_dir() / "data")


def get_logs_dir() -> Path:
    return ensure_dir(get_app_dir() / "logs")


def get_config_dir() -> Path:
    return ensure_dir(get_app_dir() / "config")


def get_exports_dir() -> Path:
    return ensure_dir(get_app_dir() / "exports")


def ensure_runtime_dirs() -> None:
    get_app_dir(); get_data_dir(); get_logs_dir(); get_config_dir(); get_exports_dir()
