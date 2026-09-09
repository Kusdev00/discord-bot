"""
Bump notification scheduler and reminder service - Python 3.9 compatible.

Reminder model (role-based, no DMs):
- A single pingable role (BUMP_PING_ROLE_ID) is pinged in the notification
  channel - no per-user pings and no direct messages.
- Disboard reminder fires every 2 hours after a Disboard bump.
- When Carl-bot AND Disboard are both due in the same scheduler pass (the
  6-hour mark when both were bumped together), ONE combined message pings
  the role for both instead of two separate pings.

Timing guarantees:
- Timestamps in bump_state are unix epoch seconds, so SQLite comparisons are exact.
- Each due reminder is atomically *claimed* before sending, so two scheduler
  passes (or two bot instances) can never both send it.
- reminder_sent is only set after the message actually went out; failed
  deliveries release the claim so the reminder retries on the next pass.
"""

import asyncio
from typing import Optional

import discord

from bot.config.bump_config import CARL_COOLDOWN, DISBOARD_COOLDOWN, BUMP_PING_ROLE_ID
from bot.database.bump_db import (
    get_all_pending_bumps,
    claim_due_reminder,
    release_claim,
    mark_reminder_sent,
    get_guild_settings,
    get_notification_channel,
)
from bot.logging_config import get_logger

logger = get_logger(__name__)

# Check interval in seconds
CHECK_INTERVAL = 30

# How long a claim is held while trying to deliver a reminder
CLAIM_HOLD_SECONDS = 300

# Service display names
SERVICE_DISPLAY = {
    "carl": "Carl-bot",
    "disboard": "Disboard",
}

# Reminder message templates (the ping role mention is prepended on send)
REMINDER_TEMPLATES = {
    "carl": "🔔 **Carl-bot bump is ready!** Bump the server with `/bump`.",
    "disboard": "🔔 **Disboard bump is ready!** Bump the server with `/bump`.",
}
COMBINED_TEMPLATE = (
    "🔔 **Carl-bot AND Disboard bumps are both ready!**\n"
    "Bump the server with `/bump` for each."
)


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

            # If the OTHER service is also due and claimable right now, claim it
            # too and send one combined message instead of two separate pings.
            # (Disboard's 2h cycle and Carl's 6h cycle align on the 6th hour.)
            other = "disboard" if service == "carl" else "carl"
            other_claimed = False
            if any(p["guild_id"] == guild_id and p["service"] == other for p in pending):
                other_claimed = await claim_due_reminder(guild_id, other, CLAIM_HOLD_SECONDS)

            services = [service, other] if other_claimed else [service]

            try:
                delivered = await self._send_reminder(guild_id, services)
            except Exception as e:
                logger.exception("Error sending %s reminder for guild %d: %s", service, guild_id, e)
                delivered = False

            if delivered:
                for svc in services:
                    await mark_reminder_sent(guild_id, svc)
                logger.info(
                    "Completed %s reminder for guild %d",
                    "+".join(services),
                    guild_id,
                )
            else:
                # Nothing delivered: release the claims so the next pass retries
                await release_claim(guild_id, service)
                if other_claimed:
                    await release_claim(guild_id, other)
                logger.warning("Could not deliver %s reminder for guild %d; will retry", service, guild_id)

    async def _resolve_channel(self, guild_id: int) -> Optional[discord.TextChannel]:
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

    def _build_reminder_embed(self, guild: discord.Guild, services: list) -> discord.Embed:
        """Build the reminder embed for one or both services."""
        if len(services) == 2:
            text = COMBINED_TEMPLATE
            title = "🔔 Carl-bot + Disboard Bump Ready"
        else:
            service = services[0]
            service_name = SERVICE_DISPLAY.get(service, service.capitalize())
            text = REMINDER_TEMPLATES.get(
                service,
                "🔔 **{} bump is ready!** Bump the server with `/bump`.".format(service.capitalize()),
            )
            title = "🔔 {} Bump Ready".format(service_name)

        embed = discord.Embed(
            description=text,
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name=title)
        embed.set_footer(text="Guild: {}".format(guild.name))
        return embed

    async def _send_reminder(self, guild_id: int, services: list) -> bool:
        """Deliver a reminder pinging the Bump ping role. Returns True only if sent."""
        channel = await self._resolve_channel(guild_id)
        if channel is None:
            return False

        embed = self._build_reminder_embed(channel.guild, services)

        # Ping the configured role (targeted allowed_mentions so the ping works
        # even if the role is not mentionable by @everyone).
        role = channel.guild.get_role(BUMP_PING_ROLE_ID)
        if role is not None:
            content = "{} {}".format(role.mention, embed.description)
            allowed = discord.AllowedMentions(roles=[role], users=False, everyone=False)
        else:
            # Role not found in this guild: announce without a ping rather than
            # dropping the reminder entirely.
            content = None
            allowed = discord.AllowedMentions.none()
            logger.warning(
                "Bump ping role %d not found in guild %d; sending reminder without a ping",
                BUMP_PING_ROLE_ID,
                guild_id,
            )

        try:
            await channel.send(content=content, embed=embed, allowed_mentions=allowed)
            logger.info(
                "Sent %s reminder (role ping) for guild %d",
                "+".join(services),
                guild_id,
            )
            return True
        except discord.Forbidden:
            logger.warning("No permission to send reminder in channel %d for guild %d", channel.id, guild_id)
            return False
        except discord.HTTPException as e:
            logger.exception("Failed to send reminder for guild %d: %s", guild_id, e)
            return False


async def send_test_reminder(bot, guild_id: int, service: str) -> bool:
    """Send a test reminder immediately (for testing)."""
    scheduler = BumpScheduler(bot)
    return await scheduler._send_reminder(guild_id, [service])
