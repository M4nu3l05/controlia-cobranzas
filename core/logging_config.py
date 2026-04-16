from __future__ import annotations

import logging
import os
from pathlib import Path

from .paths import get_logs_dir


def configure_logging() -> Path:
    logs_dir = get_logs_dir()
    log_file = logs_dir / "app.log"

    root = logging.getLogger()
    if root.handlers:
        return log_file

    root.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    # If app.log is locked or has restrictive permissions on this machine,
    # fallback to a process-specific file so startup never fails.
    file_handler = None
    for candidate in (
        log_file,
        logs_dir / f"app_{os.getpid()}.log",
        Path.cwd() / f"app_{os.getpid()}.log",
    ):
        try:
            file_handler = logging.FileHandler(candidate, encoding="utf-8")
            log_file = candidate
            break
        except OSError:
            continue

    if file_handler is not None:
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)
    return log_file
