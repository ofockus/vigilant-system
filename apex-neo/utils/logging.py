"""
Loguru-based structured logging setup.

Console output with color + rotating file logs. Call setup_logging() once at boot.
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def setup_logging(log_dir: Path, level: str = "INFO") -> None:
    """Configure loguru with console + rotating file sinks."""
    logger.remove()

    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    logger.add(sys.stderr, format=fmt, level=level, colorize=True)

    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_dir / "apex-neo.log",
        format=fmt,
        level=level,
        rotation="50 MB",
        retention="7 days",
        compression="gz",
        serialize=False,
    )

    logger.info("Logging initialized | level={} dir={}", level, log_dir)
