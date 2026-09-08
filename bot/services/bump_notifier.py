"""
Bump notification scheduler and reminder service.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional
import discord
from bot.database.bump_db import (
    get_all_pending_bumps,
    mark_reminder_sent,
    get_guild_settings,
    get_notification_channel,
    is_guild_enabled,
    should_mention_users,
    get_opted_in_users,
    count_opted_in_users,
)
from bot.config.bump_config import CARL_COOLDOWN, DISBOARD_COOLDOWN, SERVICE_CARL, SERVICE_DISBOARD
from bot.database.bump_db import mark_reminder_sent
from bot.logging_config import get_logger

logger = get_logger(__name__)

# Check interval in seconds
CHECK_INTERVAL = 30

# Maximum mentions per message (Discord limit)
MAX_MENTIONS_PER_MESSAGE = 50

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


class BumpScheduler:
    """Background scheduler for bump reminders."""

    def __init__(self, bot):
        self.bot = bot
        self.task: Optional[asyncio.Task] = None
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
        try:
            pending = await get_all_pending_bumps()
            if not pending:
                return

            logger.debug("Found %d pending bump reminders", len(pending))

            for state in pending:
                guild_id = state["guild_id"]
                service = state["service"]

                # Verify guild still enabled
                if not await is_guild_enabled(guild_id):
                    continue

                # Check if service still enabled
                settings = await get_guild_settings(guild_id)
                if not settings.get("enabled", True):
                    continue

                # Send reminder
                success = await self._send_reminder(state)
                if success:
                    await mark_reminder_sent(state["guild_id"], state["service"])

        except Exception as e:
            logger.exception("Error checking reminders: %s", e)

    async def _send_reminder(self, state: dict) -> bool:
        """Send a reminder notification for a bump."""
        try:
            guild_id = state["guild_id"]
            service = state["service"]

            # Get notification channel
            channel_id = await get_notification_channel(state["guild_id"])
            if not channel_id:
                logger.warning("No notification channel set for guild %d", state["guild_id"])
                return False

            channel = self.bot.get_channel(channel_id)
            if not channel:
                logger.warning("Notification channel %d not found for guild %d", channel_id, state["guild_id"])
                return False

            # Check bot permissions
            perms = channel.permissions_for(channel.guild.me)
            if not perms.send_messages or not perms.embed_links:
                logger.warning("Missing permissions in channel %d for guild %d", channel_id, state["guild_id"])
                return False

            # Build mention string
            mention_str = ""
            if await should_mention_users(state["guild_id"]):
                opted_in = await get_opted_in_users(state["guild_id"])
                if opted_in:
                    # Chunk mentions to respect Discord limits
                    mention_chunks = self._chunk_mentions(opted_in)
                    if mention_chunks:
                        mention_str = " ".join(mention_chunks[0]) + "\n\n"

            # Build reminder message
            service_name = SERVICE_DISPLAY.get(state["service"], state["service"].capitalize())
            template = REMINDER_TEMPLATES.get(state["service"], f"🔔 **{state['service'].capitalize()} bump is ready!**\n\nYou can bump the server again using `/bump`.")

            message = f"{mention_str}{template}"

            # Create embed with timestamp
            embed = discord.Embed(
                description=template,
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow(),
            )
            embed.set_author(name=f"🔔 {state['service'].capitalize()} Bump Ready")
            embed.set_footer(text=f"Guild: {channel.guild.name}")

            try:
                await channel.send(content=mention_str if mention_str else None, embed=embed)
                logger.info("Sent %s reminder for guild %d", state["service"], state["guild_id"])
                return True
            except discord.Forbidden:
                logger.warning("No permission to send reminder in channel %d", channel_id)
                return False
            except discord.HTTPException as e:
                logger.exception("Failed to send reminder: %s", e)
                return False

        except Exception as e:
            logger.exception("Error sending reminder: %s", e)
            return False

    def _chunk_mentions(self, user_ids: list) -> list:
        """Split user IDs into chunks for Discord mention limits."""
        chunks = []
        current_chunk = []

        for uid in user_ids:
            mention = f"<@{uid}>"
            current_chunk.append(mention)

            if len(current_chunk) >= MAX_MENTIONS_PER_MESSAGE:
                chunks.append(current_chunk)
                current_chunk = []

        if current_chunk:
            chunks.append(current_chunk)

        return chunks


async def send_test_reminder(bot, guild_id: int, service: str) -> bool:
    """Send a test reminder immediately (for testing)."""
    from bot.database.bump_db import get_notification_channel, is_guild_enabled, should_mention_users, get_opted_in_users

    # Temporarily set up a mock state for testing
    mock_state = {
        "guild_id": guild_id,
        "service": service,
    }

    # Create a mock bot-like object with get_channel
    class MockBot:
        def get_channel(self, channel_id):
            return bot.get_channel(channel_id)

    mock_bot = MockBot()
    scheduler = BumpScheduler(mock_bot)
    return await scheduler._send_reminder({"guild_id": guild_id, "service": service})