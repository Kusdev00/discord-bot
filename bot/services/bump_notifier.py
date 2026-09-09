"""
Bump notification scheduler and reminder service - Python 3.9 compatible.

Reminder model (per-person waitlist):
- When someone bumps with Carl-bot or Disboard, they are placed on a
  waitlist with a personal cooldown (6h Carl / 2h Disboard).
- When their time is up, they get pinged personally in the notification
  channel and removed from the list.
- Because Carl-bot's cooldown is per-user, multiple people can be queued
  at once; each is pinged individually and exactly once.

Timing guarantees:
- ping_at is a unix epoch second, so SQLite comparisons are exact.
- Each due entry is atomically *claimed* before pinging, so two scheduler
  passes (or two bot instances) can never both ping the same person.
- A failed delivery releases the claim so the next pass retries; the entry
  is only deleted after the ping actually went out.
"""

import asyncio
from typing import Dict, List, Optional

import discord

from bot.config.bump_config import CARL_COOLDOWN, DISBOARD_COOLDOWN
from bot.database.bump_db import (
    get_due_waitlist,
    claim_waitlist_entry,
    release_waitlist_entry,
    remove_from_waitlist,
    get_guild_settings,
    get_notification_channel,
)
from bot.logging_config import get_logger

logger = get_logger(__name__)

# Check interval in seconds
CHECK_INTERVAL = 30

# How long a claim is held while trying to deliver a ping
CLAIM_HOLD_SECONDS = 300

# Pings between small pauses (Discord rate limits rapid-fire sends)
PINGS_PER_BURST = 5
BURST_PAUSE_SECONDS = 1.5

# Service display names
SERVICE_DISPLAY = {
    "carl": "Carl-bot",
    "disboard": "Disboard",
}

# Per-person reminder text
REMINDER_TEXT = "🔔 **{service} bump is ready!** You can bump the server again with `/bump`."


def cooldown_for(service: str):
    """Cooldown timedelta for a service, sourced from bump_config."""
    return CARL_COOLDOWN if service == "carl" else DISBOARD_COOLDOWN


def cooldown_hours(service: str) -> int:
    """Cooldown for a service in whole hours."""
    return int(cooldown_for(service).total_seconds() // 3600)


class BumpScheduler:
    """Background scheduler that pings people whose bump cooldown is up."""

    def __init__(self, bot):
        self.bot = bot
        self.task = None  # type: Optional[asyncio.Task]
        self.running = False

    async def start(self) -> None:
        """Start the scheduler."""
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._run())
        logger.info("Bump scheduler started")

    async def stop(self) -> None:
        """Stop the scheduler."""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Bump scheduler stopped")

    async def _run(self) -> None:
        """Main scheduler loop."""
        while self.running:
            try:
                await self._check_and_ping()
            except Exception as e:
                logger.exception("Error in bump scheduler: %s", e)

            await asyncio.sleep(CHECK_INTERVAL)

    async def _check_and_ping(self) -> None:
        """Find due waitlist entries and personally ping each person."""
        due = await get_due_waitlist()
        if not due:
            return

        logger.debug("Found %d due waitlist entries", len(due))

        # Group by guild so each channel is resolved once
        by_guild = {}  # type: Dict[int, List[Dict]]
        for entry in due:
            by_guild.setdefault(entry["guild_id"], []).append(entry)

        for guild_id, entries in by_guild.items():
            settings = await get_guild_settings(guild_id)
            if not settings.get("enabled", True):
                continue

            channel = await self._resolve_channel(guild_id)
            if channel is None:
                # No channel to ping in: leave entries unclaimed so they retry
                # once a channel is configured (they are not due-filtered again).
                continue

            delivered = 0
            for idx, entry in enumerate(entries, 1):
                # Atomic claim: only one pass may ping this person now.
                if not await claim_waitlist_entry(entry["id"], CLAIM_HOLD_SECONDS):
                    continue  # claimed elsewhere or raced

                try:
                    await self._ping_person(channel, entry)
                    delivered += 1
                    await remove_from_waitlist(entry["id"])
                except Exception as e:
                    logger.exception("Failed to ping user %d for %s bump: %s", entry["user_id"], entry["service"], e)
                    await release_waitlist_entry(entry["id"])

                if idx % PINGS_PER_BURST == 0 and idx < len(entries):
                    await asyncio.sleep(BURST_PAUSE_SECONDS)

            if delivered:
                logger.info("Pinged %d/%d due bumpers in guild %d", delivered, len(entries), guild_id)

    async def _resolve_channel(self, guild_id: int) -> Optional[discord.TextChannel]:
        """Resolve the configured notification channel and check permissions."""
        channel_id = await get_notification_channel(guild_id)
        if not channel_id:
            logger.debug("No notification channel set for guild %d", guild_id)
            return None

        channel = self.bot.get_channel(channel_id)
        if not channel:
            logger.warning("Notification channel %d not found for guild %d", channel_id, guild_id)
            return None

        perms = channel.permissions_for(channel.guild.me)
        if not perms.send_messages:
            logger.warning("Missing send permission in channel %d for guild %d", channel_id, guild_id)
            return None

        return channel

    async def _ping_person(self, channel: discord.TextChannel, entry: Dict) -> None:
        """Ping one person whose cooldown expired. Raises on failure."""
        service_name = SERVICE_DISPLAY.get(entry["service"], entry["service"].capitalize())
        content = "<@{}> {}".format(entry["user_id"], REMINDER_TEXT.format(service=service_name))

        await channel.send(
            content=content,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        logger.info(
            "Pinged user %d: %s cooldown expired (guild %d)",
            entry["user_id"],
            service_name,
            entry["guild_id"],
        )


async def send_test_ping(bot, guild_id: int, user_id: int, service: str = "carl") -> bool:
    """Send a sample reminder ping for a user (for testing)."""
    scheduler = BumpScheduler(bot)
    channel = await scheduler._resolve_channel(guild_id)
    if channel is None:
        return False
    try:
        await scheduler._ping_person(
            channel,
            {"guild_id": guild_id, "user_id": user_id, "service": service, "id": 0},
        )
        return True
    except Exception:
        return False
