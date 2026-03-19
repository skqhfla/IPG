from __future__ import annotations

import logging
from pathlib import Path

from core.config import LogMode


def build_logger(
    *,
    name: str,
    log_mode: LogMode,
    log_path: Path,
) -> logging.Logger | None:

    if log_mode == LogMode.NO_LOG:
        return None

    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.propagate = False

    if log_mode == LogMode.DEBUG:
        level = logging.DEBUG
    else:
        level = logging.INFO

    logger.setLevel(level)

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger