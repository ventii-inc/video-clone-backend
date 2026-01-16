"""Structured logging configuration for the application."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.utils.environment import is_debug


def setup_logger(
    name: str = "video-clone",
    log_file: str | None = None,
    log_level: str | None = None,
) -> logging.Logger:
    """Configure and return the application logger.

    Args:
        name: Logger name
        log_file: Path to log file (default: from LOG_FILE env or logs/app.log)
        log_level: Log level (default: from LOG_LEVEL env or DEBUG for local, INFO for prod)

    Returns:
        Configured logger instance
    """
    # Determine log level
    if log_level is None:
        log_level = os.getenv("LOG_LEVEL", "DEBUG" if is_debug() else "INFO")

    level = getattr(logging, log_level.upper(), logging.INFO)

    # Create logger
    log = logging.getLogger(name)
    log.setLevel(level)

    # Prevent duplicate handlers
    if log.handlers:
        return log

    # Log format
    log_format = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(log_format)
    log.addHandler(console_handler)

    # File handler (only in non-debug or if explicitly configured)
    if log_file is None:
        log_file = os.getenv("LOG_FILE", "logs/app.log")

    if log_file:
        try:
            # Ensure log directory exists
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            # Rotating file handler (10MB max, keep 5 backups)
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=10 * 1024 * 1024,  # 10MB
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(log_format)
            log.addHandler(file_handler)
        except Exception as e:
            log.warning(f"Failed to create file handler for {log_file}: {e}")

    # Prevent propagation to root logger
    log.propagate = False

    return log


# Global logger instance
logger = setup_logger()


def get_logger(name: str) -> logging.Logger:
    """Get a child logger with the given name.

    Args:
        name: Logger name (will be prefixed with 'video-clone.')

    Returns:
        Logger instance
    """
    return logging.getLogger(f"video-clone.{name}")
