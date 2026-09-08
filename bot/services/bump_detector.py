"""
Bump detection logic for Carl-bot and Disboard.
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

# Compile patterns once
CARL_SUCCESS_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(kw) for kw in ["bump successful", "successfully bumped", "server bumped", "bump reminder", "next bump"]) + r")\b",
    re.IGNORECASE
)
CARL_FAILURE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(kw) for kw in ["cooldown", "wait", "try again", "already bumped", "please wait"]) + r")\b",
    re.IGNORECASE
)

DISBOARD_SUCCESS_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(kw) for kw in ["bump done", "successfully bumped", "server has been bumped", "bump again in", "next bump"]) + r")\b",
    re.IGNORECASE
)
DISBOARD_FAILURE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(kw) for kw in ["cooldown", "wait", "try again", "already bumped", "please wait"]) + r")\b",
    re.IGNORECASE
)


def is_carl_bump_success(message: discord.Message) -> bool:
    """
    Determine if a message represents a successful Carl-bot bump.
    
    Checks:
    - Message author is Carl-bot
    - Message indicates successful bump (not cooldown/failure)
    """
    if message.author.id != 235148962103951360:
        return False

    # Check content
    content = message.content.lower()

    # Explicit failure indicators
    if CARL_FAILURE_PATTERN.search(content):
        logger.debug("Carl bump failed (failure keyword): %s", content[:100])
        return False

    # Check embeds for success indicators
    for embed in message.embeds:
        # Check embed title
        if embed.title and CARL_SUCCESS_PATTERN.search(embed.title.lower()):
            logger.debug("Carl bump success (embed title): %s", embed.title)
            return True

        # Check embed description
        if embed.description and CARL_SUCCESS_PATTERN.search(embed.description.lower()):
            logger.debug("Carl bump success (embed description): %s", embed.description[:100])
            return True

        # Check embed fields
        for field in embed.fields:
            if field.value and CARL_SUCCESS_PATTERN.search(field.value.lower()):
                logger.debug("Carl bump success (embed field): %s", field.value[:100])
                return True

    # Check plain content for success
    if CARL_SUCCESS_PATTERN.search(content):
        logger.debug("Carl bump success (content): %s", content[:100])
        return True

    # Check for components/buttons that indicate success
    for component in message.components:
        for item in component.children:
            if hasattr(item, 'label') and item.label:
                if "bump" in item.label.lower() and "ready" not in item.label.lower():
                    # Button might indicate bump availability, not success
                    pass

    return False


def is_disboard_bump_success(message: discord.Message) -> bool:
    """
    Determine if a message represents a successful Disboard bump.
    
    Checks:
    - Message author is Disboard
    - Message indicates successful bump (not cooldown/failure)
    """
    if message.author.id != 302050872383242240:
        return False

    content = message.content.lower()

    # Explicit failure indicators
    if DISBOARD_FAILURE_PATTERN.search(content):
        logger.debug("Disboard bump failed (failure keyword): %s", content[:100])
        return False

    # Check embeds for success indicators
    for embed in message.embeds:
        # Check embed title
        if embed.title and DISBOARD_SUCCESS_PATTERN.search(embed.title.lower()):
            logger.debug("Disboard bump success (embed title): %s", embed.title)
            return True

        # Check embed description
        if embed.description and DISBOARD_SUCCESS_PATTERN.search(embed.description.lower()):
            logger.debug("Disboard bump success (embed description): %s", embed.description[:100])
            return True

        # Check embed fields
        for field in embed.fields:
            if field.value and DISBOARD_SUCCESS_PATTERN.search(field.value.lower()):
                logger.debug("Disboard bump success (embed field): %s", field.value[:100])
                return True

    # Check plain content for success
    if DISBOARD_SUCCESS_PATTERN.search(content):
        logger.debug("Disboard bump success (content): %s", content[:100])
        return True

    return False


async def detect_bump(message: discord.Message) -> Optional[str]:
    """
    Detect if a message is a successful bump from Carl-bot or Disboard.
    
    Returns:
        'carl' if Carl-bot bump success
        'disboard' if Disboard bump success
        None if not a successful bump
    """
    if is_carl_bump_success(message):
        return "carl"
    if is_disboard_bump_success(message):
        return "disboard"
    return None


def is_bump_command(message: discord.Message) -> bool:
    """Check if message is a bump command from a user."""
    content = message.content.strip().lower()
    return content in ("/bump", "!bump") or content.startswith("/bump ")


def debug_bump_detection(message: discord.Message) -> dict:
    """
    Debug information for bump detection.
    Returns detailed analysis of why a message was/wasn't detected as a bump.
    """
    result = {
        "author_id": message.author.id,
        "author_name": str(message.author),
        "content": message.content[:200],
        "has_embeds": len(message.embeds) > 0,
        "is_carl": message.author.id == 235148962103951360,
        "is_disboard": message.author.id == 302050872383242240,
        "carl_success": False,
        "disboard_success": False,
        "carl_failure_keywords": [],
        "disboard_failure_keywords": [],
        "carl_success_keywords": [],
        "disboard_success_keywords": [],
    }

    content = message.content.lower()

    # Check failure keywords
    result["carl_failure_keywords"] = [kw for kw in ["cooldown", "wait", "try again", "already bumped", "please wait"] if kw in content]
    result["disboard_failure_keywords"] = [kw for kw in ["cooldown", "wait", "try again", "already bumped", "please wait"] if kw in content]

    # Check success keywords
    result["carl_success_keywords"] = [kw for kw in ["bump successful", "successfully bumped", "server bumped", "bump reminder", "next bump"] if kw in content]
    result["disboard_success_keywords"] = [kw for kw in ["bump done", "successfully bumped", "server has been bumped", "bump again in", "next bump"] if kw in content]

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