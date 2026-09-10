"""
Bump system configuration - Python 3.9 compatible.
"""

from datetime import timedelta
from typing import List

# Bot IDs
CARL_BOT_ID = 235148962103951360
DISBOARD_BOT_ID = 302050872383242240

# Cooldowns
CARL_COOLDOWN = timedelta(hours=6)
DISBOARD_COOLDOWN = timedelta(hours=2)

# Bumper identity resolution: how often to re-fetch a bump confirmation whose
# invoking user wasn't in the cached interaction metadata (fresh fetches of the
# same message usually carry it). Retrying stops once the cooldown window the
# confirmation belongs to has passed - a late reminder would be pointless - or
# after the hard cap below, whichever comes first.
BUMP_IDENTITY_RETRY_LIMIT = 7 * 24 * 60 * 60  # absolute cap: 7 days
BUMP_IDENTITY_RETRY_DELAY = 60  # seconds between retry passes

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