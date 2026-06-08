from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from .config import APP_LOG_PATH, ERROR_LOG_PATH, ensure_log_dir


_HANDLER_MARKER = "_dart_lens_handler"


def configure_logging() -> None:
    ensure_log_dir()
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(min(level, logging.INFO))

    if not _has_configured_handler(root_logger, "app_file"):
        app_handler = RotatingFileHandler(
            APP_LOG_PATH,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        app_handler.setLevel(level)
        app_handler.addFilter(_MaxLevelFilter(logging.ERROR))
        app_handler.setFormatter(_formatter())
        setattr(app_handler, _HANDLER_MARKER, "app_file")
        root_logger.addHandler(app_handler)

    if not _has_configured_handler(root_logger, "error_file"):
        error_handler = RotatingFileHandler(
            ERROR_LOG_PATH,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(_formatter())
        setattr(error_handler, _HANDLER_MARKER, "error_file")
        root_logger.addHandler(error_handler)

    for logger_name in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def _formatter() -> logging.Formatter:
    return logging.Formatter(
        "%(asctime)s %(levelname)s [%(process)d:%(threadName)s] "
        "%(name)s:%(lineno)d - %(message)s"
    )


class _MaxLevelFilter(logging.Filter):
    def __init__(self, exclusive_max_level: int) -> None:
        super().__init__()
        self.exclusive_max_level = exclusive_max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < self.exclusive_max_level


def _has_configured_handler(logger: logging.Logger, handler_name: str) -> bool:
    return any(getattr(handler, _HANDLER_MARKER, None) == handler_name for handler in logger.handlers)
