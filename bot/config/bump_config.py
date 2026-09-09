"""
Bump system configuration - Python 3.9 compatible.
"""

from datetime import timedelta
from typing import List

# Bot IDs
CARL_BOT_ID = 235148962103951360
DISBOARD_BOT_ID = 302050872383242240

# Role pinged for bump reminders (must be pingable or the bot needs
# allowed_mentions to ping it - handled in the notifier)
BUMP_PING_ROLE_ID = 1547316833365926100

# Cooldowns
CARL_COOLDOWN = timedelta(hours=6)
DISBOARD_COOLDOWN = timedelta(hours=2)

# Detection keywords
CARL_SUCCESS_KEYWORDS: List[str] = [
    "bump successful",
    "successfully bumped",
    "server bumped",
    "bump reminder",
    "next bump",
    "bump done",
    "bumped the server",
    "bump complete",
]

DISBOARD_SUCCESS_KEYWORDS: List[str] = [
    "bump done",
    "successfully bumped",
    "server has been bumped",
    "bump again in",
    "next bump",
]

CARL_FAILURE_KEYWORDS: List[str] = [
    "cooldown",
    "wait",
    "try again",
    "already bumped",
    "please wait",
]

DISBOARD_FAILURE_KEYWORDS: List[str] = [
    "cooldown",
    "wait",
    "try again",
    "already bumped",
    "please wait",
]