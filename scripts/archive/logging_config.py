"""
Logging configuration for the Discord bot.
Provides structured logging to console and file with proper formatting.
"""

import logging
import logging.handlers
import sys
from pathlib import Path

from config import Config


def setup_logging() -> logging.Logger:
    """Configure and return the root logger."""
    logger = logging.getLogger("discord_bot")
    logger.setLevel(getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO))

    # Prevent duplicate handlers if called multiple times
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt=Config.LOG_FORMAT,
        datefmt=Config.LOG_DATE_FORMAT,
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO))
    logger.addHandler(console_handler)

    # File handler (if configured)
    if Config.LOG_FILE:
        log_path = Config.LOG_FILE
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)

    # Also configure discord.py logger
    discord_logger = logging.getLogger("discord")
    discord_logger.setLevel(logging.WARNING)

    # Configure http.client to reduce noise
    logging.getLogger("http.client").setLevel(logging.WARNING)

    logger.info("Logging configured (level=%s)", Config.LOG_LEVEL)
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a child logger with the given name."""
    return logging.getLogger(f"discord_bot.{name}")


# Initialize on import
setup_logging()