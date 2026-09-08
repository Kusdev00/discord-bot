"""
Bump system configuration and constants.
"""

from datetime import timedelta


# Bot IDs
CARL_BOT_ID = 235148962103951360
DISBOARD_BOT_ID = 302050872383242240

# Cooldowns
CARL_COOLDOWN = timedelta(hours=6)
DISBOARD_COOLDOWN = timedelta(hours=2)

# Defaults
DEFAULT_BUMP_NOTIFICATIONS = True
MENTION_OPTED_IN_USERS = True

# Bump service names (for database keys)
SERVICE_CARL = "carl"
SERVICE_DISBOARD = "disboard"

# Detection keywords (customizable)
CARL_SUCCESS_KEYWORDS = [
    "bump successful",
    "successfully bumped",
    "server bumped",
    "bump reminder",
    "next bump",
]
DISBOARD_SUCCESS_KEYWORDS = [
    "bump done",
    "successfully bumped",
    "server has been bumped",
    "bump again in",
    "next bump",
]

# Failure keywords (to avoid false positives)
CARL_FAILURE_KEYWORDS = [
    "cooldown",
    "wait",
    "try again",
    "already bumped",
    "please wait",
]
DISBOARD_FAILURE_KEYWORDS = [
    "cooldown",
    "wait",
    "try again",
    "already bumped",
    "please wait",
]