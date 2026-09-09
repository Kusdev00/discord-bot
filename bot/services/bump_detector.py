"""
Bump detection logic - Python 3.9 compatible.
"""

import discord
import re
from typing import Optional
from bot.config.bump_config import (
    CARL_BOT_ID,
    DISBOARD_BOT_ID,
    CARL_SUCCESS_KEYWORDS,
    DISBOARD_SUCCESS_KEYWORDS,
    CARL_FAILURE_KEYWORDS,
    DISBOARD_FAILURE_KEYWORDS,
)
from bot.logging_config import get_logger

logger = get_logger(__name__)

# Compile patterns once for performance
CARL_SUCCESS_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(kw) for kw in CARL_SUCCESS_KEYWORDS) + r")\b",
    re.IGNORECASE,
)
CARL_FAILURE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(kw) for kw in CARL_FAILURE_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

DISBOARD_SUCCESS_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(kw) for kw in DISBOARD_SUCCESS_KEYWORDS) + r")\b",
    re.IGNORECASE,
)
DISBOARD_FAILURE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(kw) for kw in DISBOARD_FAILURE_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def is_carl_bump_success(message: discord.Message) -> bool:
    """Determine if a message represents a successful Carl-bot bump."""
    if message.author.id != CARL_BOT_ID:
        return False

    content = message.content.lower()

    # Explicit failure indicators
    if CARL_FAILURE_PATTERN.search(content):
        logger.debug("Carl bump failed (failure keyword): %s", content[:100])
        return False

    # Check embeds for success indicators
    for embed in message.embeds:
        if embed.title and CARL_SUCCESS_PATTERN.search(embed.title.lower()):
            logger.debug("Carl bump success (embed title): %s", embed.title)
            return True
        if embed.description and CARL_SUCCESS_PATTERN.search(embed.description.lower()):
            logger.debug("Carl bump success (embed description): %s", embed.description[:100])
            return True
        for field in embed.fields:
            if field.value and CARL_SUCCESS_PATTERN.search(field.value.lower()):
                logger.debug("Carl bump success (embed field): %s", field.value[:100])
                return True

    # Check plain content for success
    if CARL_SUCCESS_PATTERN.search(content):
        logger.debug("Carl bump success (content): %s", content[:100])
        return True

    return False


def is_disboard_bump_success(message: discord.Message) -> bool:
    """Determine if a message represents a successful Disboard bump."""
    if message.author.id != DISBOARD_BOT_ID:
        return False

    content = message.content.lower()

    if DISBOARD_FAILURE_PATTERN.search(content):
        logger.debug("Disboard bump failed (failure keyword): %s", content[:100])
        return False

    # Check embeds for success indicators
    for embed in message.embeds:
        if embed.title and DISBOARD_SUCCESS_PATTERN.search(embed.title.lower()):
            logger.debug("Disboard bump success (embed title): %s", embed.title)
            return True
        if embed.description and DISBOARD_SUCCESS_PATTERN.search(embed.description.lower()):
            logger.debug("Disboard bump success (embed description): %s", embed.description[:100])
            return True
        for field in embed.fields:
            if field.value and DISBOARD_SUCCESS_PATTERN.search(field.value.lower()):
                logger.debug("Disboard bump success (embed field): %s", field.value[:100])
                return True

    if DISBOARD_SUCCESS_PATTERN.search(content):
        logger.debug("Disboard bump success (content): %s", content[:100])
        return True

    return False


async def detect_bump(message: discord.Message) -> Optional[str]:
    """Detect if a message is a successful bump from Carl-bot or Disboard."""
    if is_carl_bump_success(message):
        return "carl"
    if is_disboard_bump_success(message):
        return "disboard"
    return None


def debug_bump_detection(message: discord.Message) -> dict:
    """Debug information for bump detection."""
    result = {
        "author_id": message.author.id,
        "author_name": str(message.author),
        "content": message.content[:200],
        "has_embeds": len(message.embeds) > 0,
        "is_carl": message.author.id == CARL_BOT_ID,
        "is_disboard": message.author.id == DISBOARD_BOT_ID,
        "carl_success": False,
        "disboard_success": False,
        "carl_failure_keywords": [],
        "disboard_failure_keywords": [],
        "carl_success_keywords": [],
        "disboard_success_keywords": [],
    }

    content = message.content.lower()

    # Check failure keywords
    result["carl_failure_keywords"] = [kw for kw in CARL_FAILURE_KEYWORDS if kw in content]
    result["disboard_failure_keywords"] = [kw for kw in DISBOARD_FAILURE_KEYWORDS if kw in content]

    # Check success keywords
    result["carl_success_keywords"] = [kw for kw in CARL_SUCCESS_KEYWORDS if kw in content]
    result["disboard_success_keywords"] = [kw for kw in DISBOARD_SUCCESS_KEYWORDS if kw in content]

    # Check embeds
    for i, embed in enumerate(message.embeds):
        embed_info = {
            "index": i,
            "title": embed.title,
            "description": embed.description[:200] if embed.description else None,
            "fields": [{"name": f.name, "value": f.value[:200]} for f in embed.fields],
        }
        result.setdefault("embeds", []).append(embed_info)

    result["carl_success"] = is_carl_bump_success(message)
    result["disboard_success"] = is_disboard_bump_success(message)

    return result