"""
Centralized configuration management for the Discord bot.
Loads and validates all environment variables with sensible defaults.
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv


def _parse_int(value: Optional[str]) -> Optional[int]:
    """Safely parse integer from string."""
    if value is None or value.strip() == "":
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


def _parse_path(value: Optional[str]) -> Optional[Path]:
    """Safely parse path from string."""
    if value is None or value.strip() == "":
        return None
    return Path(value.strip())


# Load .env from project root
PROJECT_ROOT = Path(__file__).parent
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(ENV_PATH)


class Config:
    """Bot configuration loaded from environment variables."""

    # Discord
    DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
    if not DISCORD_TOKEN:
        raise ValueError("DISCORD_TOKEN is required in .env")

    # Bot settings
    COMMAND_PREFIX: str = os.getenv("COMMAND_PREFIX", "!")
    ACTIVITY_NAME: str = os.getenv("ACTIVITY_NAME", "with welcome system")
    ACTIVITY_TYPE: str = os.getenv("ACTIVITY_TYPE", "playing")  # playing, watching, listening, streaming

    # Welcome system
    WELCOME_ENABLED: bool = os.getenv("WELCOME_ENABLED", "true").lower() == "true"
    WELCOME_CHANNEL_ID: Optional[int] = _parse_int(os.getenv("WELCOME_CHANNEL_ID"))
    WELCOME_DEFAULT_COLOR: str = os.getenv("WELCOME_DEFAULT_COLOR", "random")
    WELCOME_TEST_CHANNEL_ID: Optional[int] = _parse_int(os.getenv("WELCOME_TEST_CHANNEL_ID"))

    # Data paths
    DATA_DIR: Path = PROJECT_ROOT / "data"
    WELCOME_CONFIG_DIR: Path = DATA_DIR / "welcome"

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR: Path = PROJECT_ROOT / "logs"
    LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"

    # Development
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    TEST_GUILD_ID: Optional[int] = _parse_int(os.getenv("TEST_GUILD_ID"))

    @classmethod
    def validate(cls) -> None:
        """Validate required configuration."""
        if not cls.DISCORD_TOKEN:
            raise ValueError("DISCORD_TOKEN is required")

        # Ensure data directories exist
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)
        cls.WELCOME_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        cls.LOG_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get_activity(cls):
        """Get activity type and name for bot presence."""
        activity_types = {
            "playing": 0,
            "streaming": 1,
            "listening": 2,
            "watching": 3,
        }
        return activity_types.get(cls.ACTIVITY_TYPE.lower(), 0), cls.ACTIVITY_NAME


# Validate on import
Config.validate()