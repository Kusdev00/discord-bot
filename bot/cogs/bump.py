"""
Bump notification system cog - Python 3.9 compatible.
"""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone, timedelta
from typing import Optional

from bot.config.bump_config import (
    CARL_BOT_ID,
    DISBOARD_BOT_ID,
)
from bot.database import (
    get_guild_settings,
    update_guild_settings,
    is_guild_enabled,
    set_user_preference,
    get_user_preference_status,
    get_bump_state,
    set_next_bump_available,
    count_opted_in_users,
    record_successful_bump,
    mark_bump_message_seen,
    check_duplicate_bump,
    reset_bump_state,
    get_all_pending_bumps,
    get_all_guild_bump_states,
    simulate_bump,
    init_db,
)
from bot.services.bump_detector import detect_bump, debug_bump_detection
from bot.services.bump_notifier import BumpScheduler
from bot.logging_config import get_logger

logger = get_logger(__name__)


class BumpCog(commands.Cog):
    """Bump notification system."""

    # Command groups
    bump_notification_group = app_commands.Group(
        name="bumpnotification",
        description="Manage your bump notifications",
        guild_only=True,
    )

    bump_config_group = app_commands.Group(
        name="bumpconfig",
        description="Configure the bump system",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    bump_test_group = app_commands.Group(
        name="bumptest",
        description="Test bump system (admin only)",
        guild_only=True,
        default_permissions=discord.Permissions(administrator=True),
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.scheduler: Optional[BumpScheduler] = None

    async def cog_load(self) -> None:
        """Initialize database and start scheduler when cog loads."""
        await init_db()
        self.scheduler = BumpScheduler(self.bot)
        await self.scheduler.start()
        logger.info("Bump system database initialized and scheduler started")

    async def cog_unload(self) -> None:
        """Stop scheduler when cog unloads."""
        if self.scheduler:
            await self.scheduler.stop()
        logger.info("Bump scheduler stopped")

    # ==================== EVENT HANDLERS ====================

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Listen for successful bumps from Carl-bot and Disboard."""
        if not message.guild:
            return

        # Only process messages from Carl-bot or Disboard
        if message.author.id not in (CARL_BOT_ID, DISBOARD_BOT_ID):
            return

        # Check if bump system is enabled for this guild
        if not await is_guild_enabled(message.guild.id):
            return

        # Detect successful bump
        service = await detect_bump(message)
        if service:
            # Check for duplicate
            if await check_duplicate_bump(message.guild.id, service, message.id):
                logger.debug("Duplicate bump message ignored: %d", message.id)
                return

            # Cooldown-window guard: a real bump cannot happen twice inside the
            # service's cooldown (2h Disboard / 6h Carl-bot). Discord mirrors bump
            # confirmations across channels, so a second copy can arrive as a NEW
            # message id minutes later - ignore anything inside an active cooldown.
            bump_time = datetime.now(timezone.utc)
            state = await get_bump_state(message.guild.id, service)
            if state and state.get("next_bump_available"):
                try:
                    next_available = int(state["next_bump_available"])
                except (TypeError, ValueError):
                    next_available = None
                if next_available and next_available > int(bump_time.timestamp()) - 1:
                    logger.info(
                        "Ignored extra %s bump confirmation in guild %d (service on cooldown)",
                        service,
                        message.guild.id,
                    )
                    return

            # Record successful bump (message marked as seen first, so a repost/edit
            # of the bump bot's confirmation can never double-count a bump)
            await record_successful_bump(
                message.guild.id,
                service,
                bump_time,
            )
            await mark_bump_message_seen(message.guild.id, service, message.id)
            logger.info("Detected successful %s bump in guild %d", service, message.guild.id)
        else:
            # A bump-related message we didn't classify. Log it so the bot's exact
            # wording can be added to the detection keywords if a real bump slips by.
            texts = [message.content or ""]
            for embed in message.embeds:
                texts.extend([embed.title or "", embed.description or ""])
                texts.extend(field.value or "" for field in embed.fields)
            combined = " ".join(texts)
            if "bump" in combined.lower():
                logger.info(
                    "Ignoring %s message mentioning bump without a success match: %s",
                    message.author,
                    " ".join(combined.split())[:200],
                )


    # ==================== USER COMMANDS ====================

    @bump_notification_group.command(name="on", description="Enable bump notifications for you")
    async def bump_notification_on(self, interaction: discord.Interaction) -> None:
        """Enable bump notifications for the user."""
        await set_user_preference(interaction.guild_id, interaction.user.id, True)
        await interaction.response.send_message(
            "✅ **Bump notifications enabled!** You'll be mentioned when bumps are ready.",
            ephemeral=True,
        )

    @bump_notification_group.command(name="off", description="Disable bump notifications for you")
    async def bump_notification_off(self, interaction: discord.Interaction) -> None:
        """Disable bump notifications for the user."""
        await set_user_preference(interaction.guild_id, interaction.user.id, False)
        await interaction.response.send_message(
            "✅ **Bump notifications disabled.** You won't be mentioned for bump reminders.",
            ephemeral=True,
        )

    @bump_notification_group.command(name="status", description="Check your bump notification status")
    async def bump_notification_status(self, interaction: discord.Interaction) -> None:
        """Show your current notification status."""
        status = await get_user_preference_status(interaction.guild_id, interaction.user.id)
        enabled = status.get("enabled", True)
        updated = status.get("settings_updated_at") or status.get("updated_at")

        embed = discord.Embed(
            title="🔔 Your Bump Notification Status",
            color=discord.Color.blue() if enabled else discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(
            name="Status",
            value="🟢 **Enabled**" if enabled else "🔴 **Disabled**",
            inline=True,
        )
        if updated:
            try:
                ts = int(datetime.fromisoformat(str(updated).replace('Z', '+00:00')).timestamp())
                embed.add_field(
                    name="Last Changed",
                    value=f"<t:{ts}:R>",
                    inline=True,
                )
            except Exception:
                pass

        embed.set_footer(text="User: {}".format(interaction.user), icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ==================== ADMIN CONFIG COMMANDS ====================

    @bump_config_group.command(name="enabled", description="Enable or disable the bump system")
    @app_commands.describe(state="Enable or disable the bump system")
    @app_commands.choices(state=[
        app_commands.Choice(name="Enable", value="on"),
        app_commands.Choice(name="Disable", value="off"),
    ])
    async def bump_config_enabled(self, interaction: discord.Interaction, state: app_commands.Choice[str]) -> None:
        """Enable or disable the bump system for this server."""
        enabled = state.value == "on"
        await update_guild_settings(interaction.guild_id, enabled=enabled)

        await interaction.response.send_message(
            "✅ Bump system **{}** for this server.".format("enabled" if enabled else "disabled"),
            ephemeral=True,
        )

    @bump_config_group.command(name="channel", description="Set the notification channel")
    @app_commands.describe(channel="Channel to send bump reminders")
    async def bump_config_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        """Set the notification channel for bump reminders."""
        # Verify bot has permissions
        perms = channel.permissions_for(interaction.guild.me)
        if not perms.send_messages or not perms.embed_links:
            await interaction.response.send_message(
                "❌ I don't have permission to send messages and embeds in {}!".format(channel.mention),
                ephemeral=True,
            )
            return

        await update_guild_settings(interaction.guild_id, notification_channel_id=channel.id)

        await interaction.response.send_message(
            "✅ Bump notification channel set to {}".format(channel.mention),
            ephemeral=True,
        )

    @bump_config_group.command(name="mentions", description="Toggle mentioning opted-in users")
    @app_commands.describe(state="Enable or disable user mentions in notifications")
    @app_commands.choices(state=[
        app_commands.Choice(name="Enable", value="on"),
        app_commands.Choice(name="Disable", value="off"),
    ])
    async def bump_config_mentions(self, interaction: discord.Interaction, state: app_commands.Choice[str]) -> None:
        """Toggle whether to mention opted-in users in notifications."""
        enabled = state.value == "on"
        await update_guild_settings(interaction.guild_id, mention_opted_in_users=enabled)

        await interaction.response.send_message(
            "✅ User mentions in bump notifications **{}**".format("enabled" if enabled else "disabled"),
            ephemeral=True,
        )

    @bump_config_group.command(name="view", description="View current bump configuration")
    async def bump_config_view(self, interaction: discord.Interaction) -> None:
        """View current bump configuration."""
        settings = await get_guild_settings(interaction.guild_id)
        channel_id = settings.get("notification_channel_id")
        channel = interaction.guild.get_channel(channel_id) if channel_id else None

        # Get user counts
        opted_in = await count_opted_in_users(interaction.guild_id)

        embed = discord.Embed(
            title="🔔 Bump System Configuration",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="🔧 Status",
            value="🟢 Enabled" if settings.get("enabled", True) else "🔴 Disabled",
            inline=True,
        )

        embed.add_field(
            name="📍 Notification Channel",
            value=channel.mention if channel else "`Not set`",
            inline=True,
        )

        embed.add_field(
            name="👤 User Mentions",
            value="🟢 Enabled" if settings.get("mention_opted_in_users", True) else "🔴 Disabled",
            inline=True,
        )

        embed.add_field(
            name="👥 Opted-in Users",
            value=str(await count_opted_in_users(interaction.guild_id)),
            inline=True,
        )

        # Show cooldown status (epoch timestamps in bump_state)
        states = await get_all_guild_bump_states(interaction.guild_id)
        for service in ["carl", "disboard"]:
            state = states.get(service)
            if state:
                next_available = state.get("next_bump_available")
                reminder_sent = state.get("reminder_sent", False)
                if next_available:
                    embed.add_field(
                        name="{} Status".format("Carl-bot" if service == "carl" else "Disboard"),
                        value=(
                            "Next: <t:{}:R>\n"
                            "Reminder: {}".format(int(next_available), "✅ Sent" if reminder_sent else "⏳ Pending")
                        ),
                        inline=True,
                    )
                else:
                    embed.add_field(
                        name="{} Status".format("Carl-bot" if service == "carl" else "Disboard"),
                        value="⏳ No bump recorded yet",
                        inline=True,
                    )
            else:
                embed.add_field(
                    name="{} Status".format("Carl-bot" if service == "carl" else "Disboard"),
                    value="⏳ No bump recorded yet",
                    inline=True,
                )

        embed.set_footer(text="Guild: {}".format(interaction.guild.name), icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ==================== ADMIN TEST COMMANDS ====================

    @bump_test_group.command(name="cycle", description="Full fast cycle: simulate a bump, reminder due in ~1 minute")
    @app_commands.describe(service="Which service to simulate")
    @app_commands.choices(service=[
        app_commands.Choice(name="Carl-bot", value="carl"),
        app_commands.Choice(name="Disboard", value="disboard"),
    ])
    async def bump_test_cycle(self, interaction: discord.Interaction, service: app_commands.Choice[str]) -> None:
        """Simulate a bump with a ~60 second cooldown so the full
        reminder pipeline (due -> claim -> ping the Bump ping role) can be
        tested without waiting the real 2h/6h."""
        await simulate_bump(interaction.guild_id, service.value)
        due = int((datetime.now(timezone.utc) + timedelta(seconds=60)).timestamp())
        await set_next_bump_available(interaction.guild_id, service.value, due)

        await interaction.response.send_message(
            "🧪 Simulated **{}** bump with a **~1 minute** cooldown.\n"
            "The scheduler (checks every 30s) will fire the reminder in the "
            "notification channel - watch for the @Bump ping.\n"
            "Due at: <t:{}:T>".format(service.value.capitalize(), due),
            ephemeral=True,
        )

    @bump_test_group.command(name="ping", description="Send a test @Bump ping reminder now")
    async def bump_test_ping(self, interaction: discord.Interaction) -> None:
        """Send a sample reminder pinging the Bump ping role so the guild can
        verify the ping lands in the notification channel."""
        from bot.services.bump_notifier import send_test_reminder
        success = await send_test_reminder(self.bot, interaction.guild_id, "carl")
        if success:
            await interaction.response.send_message(
                "✅ Test reminder with @Bump ping sent to the notification channel!",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "❌ Failed to send test reminder. Check the notification channel, "
                "the Bump ping role, and my permissions.",
                ephemeral=True,
            )

    @bump_test_group.command(name="simulate", description="Simulate a successful bump")
    @app_commands.describe(service="Which service to simulate")
    @app_commands.choices(service=[
        app_commands.Choice(name="Carl-bot", value="carl"),
        app_commands.Choice(name="Disboard", value="disboard"),
    ])
    async def bump_test_simulate(self, interaction: discord.Interaction, service: app_commands.Choice[str]) -> None:
        """Simulate a successful bump for testing."""
        await simulate_bump(interaction.guild_id, service.value)
        await interaction.response.send_message(
            "✅ Simulated successful **{}** bump!\n"
            "Cooldown set for {} hours.\n"
            "Reminder will be sent when cooldown expires.".format(
                service.value.capitalize(),
                6 if service.value == "carl" else 2
            ),
            ephemeral=True,
        )

    @bump_test_group.command(name="reminder", description="Send a test reminder immediately")
    @app_commands.describe(service="Which reminder to test")
    @app_commands.choices(service=[
        app_commands.Choice(name="Carl-bot", value="carl"),
        app_commands.Choice(name="Disboard", value="disboard"),
    ])
    async def bump_test_reminder(self, interaction: discord.Interaction, service: app_commands.Choice[str]) -> None:
        """Send a test reminder immediately without changing cooldown."""
        from bot.services.bump_notifier import send_test_reminder
        success = await send_test_reminder(self.bot, interaction.guild_id, service.value)
        if success:
            await interaction.response.send_message(
                "✅ Test **{}** reminder sent to notification channel!".format(service.value.capitalize()),
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "❌ Failed to send test reminder. Check notification channel and permissions.",
                ephemeral=True,
            )

    @bump_test_group.command(name="detection", description="Debug bump detection for a message")
    @app_commands.describe(message_id="Message ID to analyze (optional, analyzes last bot message)")
    async def bump_test_detection(self, interaction: discord.Interaction, message_id: Optional[str] = None) -> None:
        """Debug bump detection for a specific message."""
        if message_id:
            try:
                msg_id = int(message_id)
                message = await interaction.channel.fetch_message(msg_id)
            except (ValueError, discord.NotFound):
                await interaction.response.send_message("❌ Invalid message ID or message not found.", ephemeral=True)
                return
        else:
            # Find last bot message in channel
            async for msg in interaction.channel.history(limit=20):
                if msg.author.id in (302050872383242240, 235148962103951360):
                    message = msg
                    break
            else:
                await interaction.response.send_message("❌ No recent Carl-bot or Disboard message found.", ephemeral=True)
                return

        debug_info = debug_bump_detection(message)

        embed = discord.Embed(
            title="🔍 Bump Detection Debug",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(name="Author", value="{} ({})".format(debug_info['author_name'], debug_info['author_id']), inline=True)
        embed.add_field(name="Is Carl-bot", value="✅ Yes" if debug_info['is_carl'] else "❌ No", inline=True)
        embed.add_field(name="Is Disboard", value="✅ Yes" if debug_info['is_disboard'] else "❌ No", inline=True)
        embed.add_field(name="Carl Success", value="✅ Yes" if debug_info['carl_success'] else "❌ No", inline=True)
        embed.add_field(name="Disboard Success", value="✅ Yes" if debug_info['disboard_success'] else "❌ No", inline=True)
        embed.add_field(name="Content Preview", value=debug_info['content'][:200] or "*empty*", inline=False)

        if debug_info['carl_failure_keywords']:
            embed.add_field(name="❌ Carl Failure Keywords", value=", ".join(debug_info['carl_failure_keywords']), inline=True)
        if debug_info['disboard_failure_keywords']:
            embed.add_field(name="❌ Disboard Failure Keywords", value=", ".join(debug_info['disboard_failure_keywords']), inline=True)
        if debug_info['carl_success_keywords']:
            embed.add_field(name="✅ Carl Success Keywords", value=", ".join(debug_info['carl_success_keywords']), inline=True)
        if debug_info['disboard_success_keywords']:
            embed.add_field(name="✅ Disboard Success Keywords", value=", ".join(debug_info['disboard_success_keywords']), inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bump_test_group.command(name="status", description="Show detailed bump system status")
    async def bump_test_status(self, interaction: discord.Interaction) -> None:
        """Show detailed bump system status for administrators."""
        settings = await get_guild_settings(interaction.guild_id)
        states = await get_all_guild_bump_states(interaction.guild_id)
        opted_in_count = await count_opted_in_users(interaction.guild_id)

        embed = discord.Embed(
            title="🔔 Bump System Status",
            color=discord.Color.blue() if settings.get("enabled", True) else discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="🔧 System",
            value="🟢 Enabled" if settings.get("enabled", True) else "🔴 Disabled",
            inline=True,
        )

        channel_id = settings.get("notification_channel_id")
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        embed.add_field(
            name="📍 Channel",
            value=channel.mention if channel else "`Not set`",
            inline=True,
        )

        embed.add_field(
            name="👤 Mentions",
            value="🟢 Enabled" if settings.get("mention_opted_in_users", True) else "🔴 Disabled",
            inline=True,
        )

        embed.add_field(
            name="👥 Opted In",
            value=str(await count_opted_in_users(interaction.guild_id)),
            inline=True,
        )

        # Service status
        for service in ["carl", "disboard"]:
            state = states.get(service)
            display_name = "Carl-bot" if service == "carl" else "Disboard"

            if state:
                next_available = state.get("next_bump_available")
                last_bump = state.get("last_successful_bump")
                reminder_sent = state.get("reminder_sent", False)

                value_lines = []

                if last_bump:
                    value_lines.append("Last: <t:{}:R>".format(int(last_bump)))

                if next_available:
                    value_lines.append("Next: <t:{}:R>".format(int(next_available)))

                value_lines.append("Reminder: {}".format("✅ Sent" if reminder_sent else "⏳ Pending"))

                embed.add_field(
                    name=display_name,
                    value="\n".join(value_lines),
                    inline=True,
                )
            else:
                embed.add_field(
                    name=display_name,
                    value="⏳ No bump recorded yet",
                    inline=True,
                )

        # Pending reminders
        pending = await get_all_pending_bumps()
        guild_pending = [p for p in pending if p["guild_id"] == interaction.guild_id]
        if guild_pending:
            embed.add_field(
                name="⏳ Pending Reminders",
                value="\n".join("{}: ready".format(p['service'].capitalize()) for p in guild_pending),
                inline=False,
            )

        embed.set_footer(text="Guild: {}".format(interaction.guild.name))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bump_test_group.command(name="reset", description="Reset bump cooldown for testing")
    @app_commands.describe(service="Which service to reset")
    @app_commands.choices(service=[
        app_commands.Choice(name="Carl-bot", value="carl"),
        app_commands.Choice(name="Disboard", value="disboard"),
    ])
    async def bump_test_reset(self, interaction: discord.Interaction, service: app_commands.Choice[str]) -> None:
        """Reset bump state for a service."""
        await reset_bump_state(interaction.guild_id, service.value)
        await interaction.response.send_message(
            "⚠️ Reset **{}** bump state for this server.\n"
            "Cooldown cleared, next bump available immediately.".format(service.value.capitalize()),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    """Set up the bump cog."""
    await bot.add_cog(BumpCog(bot))