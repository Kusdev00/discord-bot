"""
Core bot class with setup, event handling, and cog management.
"""

import discord
import os
import time
from discord.ext import commands

from bot.config import Config
from bot.logging_config import get_logger

logger = get_logger(__name__)


class DiscordBot(commands.Bot):
    """Main bot class with enhanced setup and error handling."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True  # Required for on_member_join
        intents.message_content = True  # Required for prefix commands
        intents.messages = True

        super().__init__(
            command_prefix=Config.COMMAND_PREFIX,
            intents=intents,
            help_command=None,  # We'll implement custom help
            activity=self._get_activity(),
            status=discord.Status.online,
            heartbeat_timeout=60.0,  # Reconnect if the gateway goes quiet (zombie-connection guard)
        )

        # Watchdog: last time we received ANY traffic from the Discord gateway.
        # A healthy connection receives frames constantly; a "zombie" connection
        # keeps the process alive but stops delivering events (messages, commands),
        # which silently breaks bump detection. Exited so systemd restarts us.
        self._last_gateway_rx = time.monotonic()

    def _get_activity(self) -> discord.Activity:
        """Create activity from config."""
        activity_types = {
            "playing": discord.ActivityType.playing,
            "streaming": discord.ActivityType.streaming,
            "listening": discord.ActivityType.listening,
            "watching": discord.ActivityType.watching,
        }
        activity_type = activity_types.get(Config.ACTIVITY_TYPE.lower(), discord.ActivityType.playing)
        return discord.Activity(type=activity_type, name=Config.ACTIVITY_NAME)

    async def setup_hook(self) -> None:
        """Called when the bot is starting up. Load cogs and sync commands."""
        logger.info("Starting bot setup...")

        # Load cogs
        await self._load_cogs()

        # Sync slash commands
        if Config.TEST_GUILD_ID:
            guild = discord.Object(id=Config.TEST_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logger.info("Synced %d commands to test guild %d", len(synced), Config.TEST_GUILD_ID)
        else:
            synced = await self.tree.sync()
            logger.info("Synced %d global commands", len(synced))

        logger.info("Bot setup complete")

    async def _load_cogs(self) -> None:
        """Load all cogs from the cogs directory."""
        cogs = [
            "bot.cogs.welcome",
            "bot.cogs.admin",
            "bot.cogs.utils",
            "bot.cogs.inviteblock",
            "bot.cogs.bump",
        ]

        for cog in cogs:
            try:
                await self.load_extension(cog)
                logger.info("Loaded cog: %s", cog)
            except Exception as e:
                logger.exception("Failed to load cog %s: %s", cog, e)

    async def on_socket_raw_receive(self, msg) -> None:
        """Track liveness: any gateway traffic means the connection is real."""
        self._last_gateway_rx = time.monotonic()

    async def on_ready(self) -> None:
        """Called when the bot is ready and connected."""
        logger.info(
            "Logged in as %s (ID: %d) | Guilds: %d",
            self.user,
            self.user.id if self.user else 0,
            len(self.guilds),
        )

        # Zombie connection guard: if ready fired but we have not received a
        # single gateway frame in over an hour, events are not being delivered.
        idle = time.monotonic() - self._last_gateway_rx
        if idle > 3600:
            logger.error(
                "No gateway traffic for %.0f minutes - zombie connection detected; "
                "exiting so systemd restarts the bot with a fresh session",
                idle / 60,
            )
            os._exit(1)

        # Log guild info in debug mode
        if Config.DEBUG:
            for guild in self.guilds:
                logger.debug("Connected to guild: %s (ID: %d, Members: %d)", guild.name, guild.id, guild.member_count)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Called when the bot joins a new guild."""
        logger.info("Joined new guild: %s (ID: %d, Members: %d)", guild.name, guild.id, guild.member_count)

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        """Called when the bot leaves a guild."""
        logger.info("Left guild: %s (ID: %d)", guild.name, guild.id)

    async def on_error(self, event: str, *args, **kwargs) -> None:
        """Global error handler for uncaught exceptions in event handlers."""
        logger.exception("Unhandled error in event %s", event)

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        """Global error handler for prefix commands."""
        if isinstance(error, commands.CommandNotFound):
            return  # Ignore unknown commands

        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You don't have permission to use this command.", delete_after=10)
            return

        if isinstance(error, commands.BotMissingPermissions):
            await ctx.send("❌ I don't have the required permissions to execute this command.", delete_after=10)
            return

        logger.exception("Command error in %s: %s", ctx.command, error)

    async def on_application_command_error(
        self,
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ) -> None:
        """Global error handler for slash commands."""
        if isinstance(error, discord.app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"⏳ Command on cooldown. Try again in {error.retry_after:.1f}s.",
                ephemeral=True,
            )
            return

        if isinstance(error, discord.app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True,
            )
            return

        if isinstance(error, discord.app_commands.BotMissingPermissions):
            await interaction.response.send_message(
                "❌ I don't have the required permissions to execute this command.",
                ephemeral=True,
            )
            return

        if isinstance(error, discord.app_commands.CheckFailure):
            await interaction.response.send_message(
                "❌ You don't meet the requirements to use this command.",
                ephemeral=True,
            )
            return

        logger.exception("Slash command error: %s", error)

        # Try to respond if not already responded
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ An unexpected error occurred. Please try again later.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "❌ An unexpected error occurred. Please try again later.",
                    ephemeral=True,
                )
        except discord.NotFound:
            pass  # Interaction expired


# Global bot instance
bot = DiscordBot()