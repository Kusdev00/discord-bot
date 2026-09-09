"""
Bump notification system cog - Python 3.9 compatible.
"""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
from typing import Optional, List

from bot.config import Config
from bot.config.bump_config import (
    CARL_BOT_ID,
    DISBOARD_BOT_ID,
    CARL_COOLDOWN,
    DISBOARD_COOLDOWN,
    SERVICE_CARL,
    SERVICE_DISBOARD,
)
from bot.database import (
    get_guild_settings,
    update_guild_settings,
    get_user_preference,
    set_user_preference,
    get_user_preference_status,
    count_opted_in_users,
    get_bump_state,
    record_successful_bump,
    reset_bump_state,
    get_all_guild_bump_states,
    simulate_bump,
    trigger_reminder_now,
    get_all_pending_bumps,
    check_duplicate_bump,
    init_db,
)
from bot.services.bump_detector import detect_bump, debug_bump_detection
from bot.services.bump_notifier import send_test_reminder
from bot.logging_config import get_logger

logger = get_logger(__name__)

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


class BumpCog(commands.Cog):
    """Bump notification system."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        """Initialize database when cog loads."""
        await init_db()
        logger.info("Bump system database initialized")

    # ==================== EVENT HANDLERS ====================

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen for successful bumps from Carl-bot and Disboard."""
        # Ignore bots, DMs, and messages without guild
        if not message.guild or message.author.bot:
            # But we DO want to process bot messages from Carl/Disboard
            if not message.author.bot:
                return

        # Skip if no guild
        if not message.guild:
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

            # Record successful bump
            bump_time = datetime.now(timezone.utc)
            await record_successful_bump(
                message.guild.id,
                service,
                bump_time,
                message.id,
            )
            logger.info("Detected successful %s bump in guild %d", service, message.guild.id)

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
        enabled = status["enabled"]
        updated = status["settings_updated_at"]

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
        if status["settings_updated_at"]:
            embed.add_field(
                name="Last Changed",
                value="<t:{}:R>".format(int(datetime.fromisoformat(status['settings_updated_at'].replace('Z', '+00:00')).timestamp())),
                inline=True,
            )
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

        # Show cooldown status
        states = await get_all_guild_bump_states(interaction.guild_id)
        for service in ["carl", "disboard"]:
            state = states.get(service)
            if state:
                next_available = state.get("next_bump_available")
                reminder_sent = state.get("reminder_sent", False)
                if next_available:
                    next_time = datetime.fromisoformat(next_available.replace('Z', '+00:00'))
                    embed.add_field(
                        name="{} Status".format("Carl-bot" if service == "carl" else "Disboard"),
                        value=(
                            "Next: <t:{}:R>\n"
                            "Reminder: {}".format(int(next_time.timestamp()), "✅ Sent" if reminder_sent else "⏳ Pending")
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
                    last_time = datetime.fromisoformat(last_bump.replace('Z', '+00:00'))
                    value_lines.append("Last: <t:{}:R>".format(int(last_time.timestamp())))

                if next_available:
                    next_time = datetime.fromisoformat(next_available.replace('Z', '+00:00'))
                    value_lines.append("Next: <t:{}:R>".format(int(next_time.timestamp())))

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