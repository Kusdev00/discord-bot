"""
Bump notification scheduler and reminder service - Python 3.9 compatible.

Timing guarantees:
- Timestamps in bump_state are unix epoch seconds, so SQLite comparisons are exact.
- Each due reminder is atomically *claimed* before sending, so two scheduler
  passes (or two bot instances) can never both send it.
- Opted-in users are pinged one message per user (rate-limit friendly) instead
  of one batched mention blob.
- reminder_sent is only set for a cycle after at least one user was actually
  pinged or the channel post went out; failed deliveries release the claim so
  the reminder retries on the next pass.
"""

import asyncio
from typing import List, Optional

import discord

from bot.config.bump_config import CARL_COOLDOWN, DISBOARD_COOLDOWN
from bot.database.bump_db import (
    get_all_pending_bumps,
    claim_due_reminder,
    release_claim,
    mark_reminder_sent,
    get_guild_settings,
    get_notification_channel,
    get_opted_in_users,
)
from bot.logging_config import get_logger

logger = get_logger(__name__)

# Check interval in seconds
CHECK_INTERVAL = 30

# Per-user pings between small pauses (Discord rate limits rapid-fire sends)
USERS_PER_BURST = 5
BURST_PAUSE_SECONDS = 1.5

# How long a claim is held while trying to deliver a reminder
CLAIM_HOLD_SECONDS = 300

# Service display names
SERVICE_DISPLAY = {
    "carl": "Carl-bot",
    "disboard": "Disboard",
}

# Reminder message templates
REMINDER_TEMPLATES = {
    "carl": "🔔 **Carl-bot bump is ready!**\n\nYou can bump the server again using `/bump`.",
    "disboard": "🔔 **Disboard bump is ready!**\n\nYou can bump the server again using `/bump`.",
}


def cooldown_hours(service: str) -> int:
    """Cooldown for a service in whole hours, sourced from bump_config."""
    return int((CARL_COOLDOWN if service == "carl" else DISBOARD_COOLDOWN).total_seconds() // 3600)


class BumpScheduler:
    """Background scheduler for bump reminders."""

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
                await self._check_and_send_reminders()
            except Exception as e:
                logger.exception("Error in bump scheduler: %s", e)

            await asyncio.sleep(CHECK_INTERVAL)

    async def _check_and_send_reminders(self) -> None:
        """Check for expired cooldowns and send reminders."""
        pending = await get_all_pending_bumps()
        if not pending:
            return

        logger.debug("Found %d pending bump reminders", len(pending))

        for state in pending:
            guild_id = state["guild_id"]
            service = state["service"]

            # Verify guild still has the bump system enabled
            settings = await get_guild_settings(guild_id)
            if not settings.get("enabled", True):
                continue

            # Atomic claim: only one pass may attempt this reminder now.
            # Also re-checks the due-condition inside the UPDATE, so a bump
            # recorded between the SELECT above and now can't fire early.
            if not await claim_due_reminder(guild_id, service, CLAIM_HOLD_SECONDS):
                continue  # not due anymore, already sent, or claimed elsewhere

            try:
                delivered = await self._send_reminder(guild_id, service)
            except Exception as e:
                logger.exception("Error sending %s reminder for guild %d: %s", service, guild_id, e)
                delivered = False

            if delivered:
                await mark_reminder_sent(guild_id, service)
                logger.info("Completed %s reminder for guild %d", service, guild_id)
            else:
                # Nothing delivered: release the claim so the next pass retries
                await release_claim(guild_id, service)
                logger.warning("Could not deliver %s reminder for guild %d; will retry", service, guild_id)

    async def _resolve_channel(self, guild_id: int) -> Optional[discord.abc.Messageable]:
        """Resolve the configured notification channel and check permissions."""
        channel_id = await get_notification_channel(guild_id)
        if not channel_id:
            logger.warning("No notification channel set for guild %d", guild_id)
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

    async def _send_reminder(self, guild_id: int, service: str) -> bool:
        """Deliver a reminder for one due bump cycle. Returns True only if something was sent."""
        channel = await self._resolve_channel(guild_id)
        if channel is None:
            return False

        service_name = SERVICE_DISPLAY.get(service, service.capitalize())
        template = REMINDER_TEMPLATES.get(
            service,
            "🔔 **{} bump is ready!**\n\nYou can bump the server again using `/bump`.".format(service.capitalize()),
        )

        embed = discord.Embed(
            description=template,
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name="🔔 {} Bump Ready".format(service_name))
        embed.set_footer(text="Guild: {}".format(channel.guild.name))

        opted_in = await get_opted_in_users(guild_id)

        # Ping each opted-in user in their own message (visible as a personal ping,
        # no shared batch). Users whose DM/channel context is irrelevant simply get
        # one ping message each in the notification channel.
        delivered_any = False
        if opted_in:
            delivered_any = await self._ping_users_individually(channel, opted_in, service_name, embed)

        # If nobody was pinged (or mentions are pointless), still post the
        # channel-level reminder so the server sees the bump is ready.
        if not delivered_any:
            try:
                await channel.send(embed=embed)
                delivered_any = True
                logger.info("Sent channel-only %s reminder for guild %d", service, guild_id)
            except discord.Forbidden:
                logger.warning("No permission to send reminder in channel %d for guild %d", channel.id, guild_id)
                return False
            except discord.HTTPException as e:
                logger.exception("Failed to send reminder embed for guild %d: %s", guild_id, e)
                return False

        return delivered_any

    async def _ping_users_individually(
        self,
        channel: discord.abc.Messageable,
        user_ids: List[int],
        service_name: str,
        embed: discord.Embed,
    ) -> bool:
        """Send one ping per user. Returns True if at least one ping was delivered."""
        delivered = 0
        for idx, uid in enumerate(user_ids, 1):
            try:
                await channel.send(
                    content="<@{}> 🔔 **{} bump is ready!** Bump the server with `/bump`.".format(uid, service_name),
                    silent=True,
                )
                delivered += 1
            except discord.Forbidden:
                logger.warning("Forbidden pinging user %d in guild channel; skipping", uid)
            except discord.HTTPException as e:
                logger.warning("Failed to ping user %d: %s", uid, e)

            # Small pause every burst to stay friendly to rate limits
            if idx % USERS_PER_BURST == 0 and idx < len(user_ids):
                await asyncio.sleep(BURST_PAUSE_SECONDS)

        if delivered:
            logger.info("Pinged %d/%d opted-in users individually", delivered, len(user_ids))
        return delivered > 0


async def send_test_reminder(bot, guild_id: int, service: str) -> bool:
    """Send a test reminder immediately (for testing)."""
    scheduler = BumpScheduler(bot)
    return await scheduler._send_reminder(guild_id, service)
