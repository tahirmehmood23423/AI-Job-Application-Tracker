"""
Centralised structured logging.

We use JSON logs in production so log aggregators (Datadog, Logtail, Grafana
Cloud, etc.) can index them. In development, the format is plain text for
readability.
"""
import logging
import sys

from pythonjsonlogger.jsonlogger import JsonFormatter

from app.config import get_settings


def configure_logging() -> None:
    """Call once at app startup."""
    settings = get_settings()

    root = logging.getLogger()
    root.setLevel(settings.log_level)

    # Wipe any default handlers so we don't double-log
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if settings.app_env == "production":
        formatter: logging.Formatter = JsonFormatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level"},
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        )

    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Quiet some noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("pdfplumber").setLevel(logging.WARNING)
    logging.getLogger("pypdf").setLevel(logging.ERROR)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
