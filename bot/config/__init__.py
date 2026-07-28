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

__all__ = ["Config", "welcome_config"]