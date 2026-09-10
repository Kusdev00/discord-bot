"""
Bump detection logic - Python 3.9 compatible.

Detection model
===============
A platform's confirmation message is accepted only when ALL of these hold:

1. The message comes from the platform's bot. The authoritative check is
   ``message.author.id == <bot id>`` (bots authored the message directly).
   For APP messages (slash-command interaction responses rendered as a bot
   message) we additionally accept ``message.application_id == <bot id>``,
   which is the stable application identity Discord sets on interaction
   messages regardless of how the author object was hydrated.
2. A SUCCESS indicator is present in the content or embeds
   (title / description / fields). Indicators are matched with a tolerant
   pattern (word boundaries, case-insensitive) so minor punctuation,
   capitalisation and Discord formatting do not matter.
3. No FAILURE indicator is present in the *sentence that carried the success
   indicator*. Bump bots routinely combine both in one message
   (e.g. Carl-bot's classic "successfully bumped ... you have to wait 6
   hours"), so a blanket failure veto would reject genuine successes. A
   standalone failure notice contains no success phrase, and is rejected.
"""
import re
from typing import List, Optional, Tuple

import discord

from bot.config.bump_config import (
    CARL_BOT_ID,
    CARL_FAILURE_KEYWORDS,
    CARL_SUCCESS_KEYWORDS,
    DISBOARD_BOT_ID,
    DISBOARD_FAILURE_KEYWORDS,
    DISBOARD_SUCCESS_KEYWORDS,
)
from bot.logging_config import get_logger

logger = get_logger(__name__)

# Compile patterns once for performance.
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

# Discord formatting (bold/italic/underline/strike/code/spoilers) that may
# wrap keywords; stripped before matching.
_MARKDOWN_RE = re.compile(r"[*_~`|>]")


def _iter_texts(message: discord.Message) -> List[str]:
    """All searchable text surfaces of a message: content + embed surfaces."""
    texts = [message.content or ""]
    for embed in message.embeds:
        texts.append(embed.title or "")
        texts.append(embed.description or "")
        for field in embed.fields:
            texts.append(field.name or "")
            texts.append(field.value or "")
    return texts


def _normalized_sentences(text: str) -> List[str]:
    """Split a text into sentences and normalise each for matching.

    Normalisation lower-cases and strips Discord markdown so formatting
    differences cannot hide a keyword. Bold like **bump** done becomes
    "bump done".
    """
    cleaned = _MARKDOWN_RE.sub(" ", text)
    parts = re.split(r"(?<=[.!?\n])\s+", cleaned)
    return [p.strip().lower() for p in parts if p.strip()]


def _author_matches(message: discord.Message, bot_id: int) -> bool:
    """True if the message was produced by the bot/application ``bot_id``.

    - ``message.author.id`` covers plain bot messages.
    - ``message.application_id`` covers APP messages (interaction responses),
      where the author object may be hydrated as a member object with a
      different-looking id, or the message may be attributed to the invoking
      user. The application id is the stable identity in that case.
    """
    if message.author.id == bot_id:
        return True
    return message.application_id == bot_id


def _match_platform(
    message: discord.Message,
    success_pattern: "re.Pattern",
    failure_pattern: "re.Pattern",
    bot_id: int,
) -> Tuple[bool, str]:
    """Core detector shared by both platforms.

    Returns (matched, reason) - reason explains the decision for logging.
    """
    if not _author_matches(message, bot_id):
        return False, f"not from this bot (author.id={message.author.id})"

    for text in _iter_texts(message):
        for sentence in _normalized_sentences(text):
            if not success_pattern.search(sentence):
                continue
            if failure_pattern.search(sentence):
                # Success phrase and failure phrase in the same sentence:
                # bots append "you have to wait 6 hours" to genuine success
                # confirmations, so this is still a success. See class doc.
                logger.debug(
                    "Success sentence also contains failure keyword; treating as success: %s",
                    sentence[:120],
                )
            return True, f"success sentence: {sentence[:120]}"

    return False, "no success phrase in content/embeds"


def is_carl_bump_success(message: discord.Message) -> bool:
    """Determine if a message represents a successful Carl-bot bump."""
    matched, reason = _match_platform(
        message, CARL_SUCCESS_PATTERN, CARL_FAILURE_PATTERN, CARL_BOT_ID
    )
    if matched:
        logger.debug("Carl bump success: %s", reason)
    else:
        logger.debug("Carl bump not matched: %s", reason)
    return matched


def is_disboard_bump_success(message: discord.Message) -> bool:
    """Determine if a message represents a successful Disboard bump."""
    matched, reason = _match_platform(
        message, DISBOARD_SUCCESS_PATTERN, DISBOARD_FAILURE_PATTERN, DISBOARD_BOT_ID
    )
    if matched:
        logger.debug("Disboard bump success: %s", reason)
    else:
        logger.debug("Disboard bump not matched: %s", reason)
    return matched


async def detect_bump(message: discord.Message) -> Optional[str]:
    """Detect if a message is a successful bump from Carl-bot or Disboard."""
    if is_carl_bump_success(message):
        return "carl"
    if is_disboard_bump_success(message):
        return "disboard"
    return None


def debug_bump_detection(message: discord.Message) -> dict:
    """Debug information for bump detection: the fields that decide detection."""
    result = {
        "author_id": message.author.id,
        "author_name": str(message.author),
        "author_bot": bool(message.author.bot),
        "application_id": message.application_id,
        "webhook_id": message.webhook_id,
        "message_type": str(message.type),
        "channel_id": message.channel.id if message.channel else None,
        "guild_id": message.guild.id if message.guild else None,
        "content": (message.content or "")[:200],
        "has_embeds": len(message.embeds) > 0,
        "is_carl": _author_matches(message, CARL_BOT_ID),
        "is_disboard": _author_matches(message, DISBOARD_BOT_ID),
        "carl_success": False,
        "disboard_success": False,
        "carl_failure_keywords": [],
        "disboard_failure_keywords": [],
        "carl_success_keywords": [],
        "disboard_success_keywords": [],
    }

    # Keyword presence across every text surface (content + embeds).
    all_texts = [t.lower() for t in _iter_texts(message)]

    result["carl_failure_keywords"] = [
        kw for kw in CARL_FAILURE_KEYWORDS if any(kw in t for t in all_texts)
    ]
    result["disboard_failure_keywords"] = [
        kw for kw in DISBOARD_FAILURE_KEYWORDS if any(kw in t for t in all_texts)
    ]
    result["carl_success_keywords"] = [
        kw for kw in CARL_SUCCESS_KEYWORDS if any(kw in t for t in all_texts)
    ]
    result["disboard_success_keywords"] = [
        kw for kw in DISBOARD_SUCCESS_KEYWORDS if any(kw in t for t in all_texts)
    ]

    # Interaction metadata: for APP messages this carries the invoking user,
    # which is how the bumper is identified for waitlist placement.
    meta = getattr(message, "interaction_metadata", None)
    if meta is not None:
        inv_user = getattr(meta, "user", None)
        result["interaction_user"] = str(inv_user) if inv_user else None
        result["interaction_user_id"] = inv_user.id if inv_user else None

    if message.reference:
        result["reference_message_id"] = message.reference.message_id

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
