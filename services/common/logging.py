"""Structured logging helpers based on structlog."""
from __future__ import annotations

import logging
from typing import Any

import structlog


def configure_logging(level: str = "INFO", json_mode: bool = True) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO))
    processors: list[Any] = [
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if json_mode:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )
