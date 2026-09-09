"""
Bot config package - re-exports from project root config.
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import Config

# Also import welcome_config
from bot.config.welcome_config import welcome_config
# Also import bump_config
from bot.config.bump_config import (
    CARL_BOT_ID,
    DISBOARD_BOT_ID,
    CARL_COOLDOWN,
    DISBOARD_COOLDOWN,
    DEFAULT_BUMP_NOTIFICATIONS,
    MENTION_OPTED_IN_USERS,
    SERVICE_CARL,
    SERVICE_DISBOARD,
    CARL_SUCCESS_KEYWORDS,
    DISBOARD_SUCCESS_KEYWORDS,
    CARL_FAILURE_KEYWORDS,
    DISBOARD_FAILURE_KEYWORDS,
)

__all__ = [
    "Config",
    "welcome_config",
    "CARL_BOT_ID",
    "DISBOARD_BOT_ID",
    "CARL_COOLDOWN",
    "DISBOARD_COOLDOWN",
    "DEFAULT_BUMP_NOTIFICATIONS",
    "MENTION_OPTED_IN_USERS",
    "SERVICE_CARL",
    "SERVICE_DISBOARD",
    "CARL_SUCCESS_KEYWORDS",
    "DISBOARD_SUCCESS_KEYWORDS",
    "CARL_FAILURE_KEYWORDS",
    "DISBOARD_FAILURE_KEYWORDS",
]