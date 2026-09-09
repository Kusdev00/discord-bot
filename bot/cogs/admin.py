"""
Administrative commands cog for bot management.
"""

import discord
from discord import app_commands
from discord.ext import commands

from bot.logging_config import get_logger

logger = get_logger(__name__)


class AdminCog(commands.Cog):
    """Administrative commands for bot management."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="sync", description="Sync slash commands (Owner only)")
    @app_commands.default_permissions(administrator=True)
    async def sync(self, interaction: discord.Interaction, guild_only: bool = True) -> None:
        """Sync slash commands to Discord."""
        await interaction.response.defer(ephemeral=True)

        if guild_only and interaction.guild:
            guild = discord.Object(id=interaction.guild.id)
            self.bot.tree.copy_global_to(guild=guild)
            await self.bot.tree.sync(guild=guild)
            await interaction.followup.send(f"✅ Synced commands to guild **{interaction.guild.name}**")
        else:
            await self.bot.tree.sync()
            await interaction.followup.send("✅ Synced global commands")

    @app_commands.command(name="reload", description="Reload a cog (Owner only)")
    @app_commands.describe(cog="Name of the cog to reload (e.g., 'welcome', 'utils', 'admin')")
    @app_commands.default_permissions(administrator=True)
    async def reload(self, interaction: discord.Interaction, cog: str) -> None:
        """Reload a cog extension."""
        await interaction.response.defer(ephemeral=True)

        cog_name = f"bot.cogs.{cog.lower()}"
        try:
            await self.bot.reload_extension(cog_name)
            await interaction.followup.send(f"✅ Reloaded cog: `{cog_name}`")
            logger.info("Reloaded cog: %s", cog_name)
        except commands.ExtensionNotLoaded:
            await interaction.followup.send(f"❌ Cog `{cog_name}` is not loaded")
        except commands.ExtensionNotFound:
            await interaction.followup.send(f"❌ Cog `{cog_name}` not found")
        except Exception as e:
            logger.exception("Failed to reload cog %s: %s", cog_name, e)
            await interaction.followup.send(f"❌ Failed to reload `{cog_name}`: {e}")

    @app_commands.command(name="load", description="Load a cog (Owner only)")
    @app_commands.describe(cog="Name of the cog to load (e.g., 'welcome', 'utils', 'admin')")
    @app_commands.default_permissions(administrator=True)
    async def load(self, interaction: discord.Interaction, cog: str) -> None:
        """Load a cog extension."""
        await interaction.response.defer(ephemeral=True)

        cog_name = f"bot.cogs.{cog.lower()}"
        try:
            await self.bot.load_extension(cog_name)
            await interaction.followup.send(f"✅ Loaded cog: `{cog_name}`")
            logger.info("Loaded cog: %s", cog_name)
        except commands.ExtensionAlreadyLoaded:
            await interaction.followup.send(f"❌ Cog `{cog_name}` is already loaded")
        except commands.ExtensionNotFound:
            await interaction.followup.send(f"❌ Cog `{cog_name}` not found")
        except Exception as e:
            logger.exception("Failed to load cog %s: %s", cog_name, e)
            await interaction.followup.send(f"❌ Failed to load `{cog_name}`: {e}")

    @app_commands.command(name="unload", description="Unload a cog (Owner only)")
    @app_commands.describe(cog="Name of the cog to unload (e.g., 'welcome', 'utils', 'admin')")
    @app_commands.default_permissions(administrator=True)
    async def unload(self, interaction: discord.Interaction, cog: str) -> None:
        """Unload a cog extension."""
        await interaction.response.defer(ephemeral=True)

        cog_name = f"bot.cogs.{cog.lower()}"
        try:
            await self.bot.unload_extension(cog_name)
            await interaction.followup.send(f"✅ Unloaded cog: `{cog_name}`")
            logger.info("Unloaded cog: %s", cog_name)
        except commands.ExtensionNotLoaded:
            await interaction.followup.send(f"❌ Cog `{cog_name}` is not loaded")
        except Exception as e:
            logger.exception("Failed to unload cog %s: %s", cog_name, e)
            await interaction.followup.send(f"❌ Failed to unload `{cog_name}`: {e}")

    @app_commands.command(name="cogs", description="List all loaded cogs")
    @app_commands.default_permissions(administrator=True)
    async def list_cogs(self, interaction: discord.Interaction) -> None:
        """List all loaded cogs and their commands."""
        embed = discord.Embed(
            title="📦 Loaded Cogs",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

        for cog_name, cog in self.bot.cogs.items():
            commands_list = [cmd.name for cmd in cog.get_app_commands()]
            embed.add_field(
                name=f"📂 {cog_name}",
                value="\n".join(f"  • `/{cmd}`" for cmd in commands_list) or "  *No commands*",
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="guilds", description="List all guilds the bot is in (Owner only)")
    @app_commands.default_permissions(administrator=True)
    async def list_guilds(self, interaction: discord.Interaction) -> None:
        """List all guilds the bot is connected to."""
        await interaction.response.defer(ephemeral=True)

        guilds = self.bot.guilds
        if not guilds:
            await interaction.followup.send("Bot is not in any guilds.")
            return

        embed = discord.Embed(
            title=f"🏰 Connected Guilds ({len(guilds)})",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

        # Sort by member count descending
        sorted_guilds = sorted(guilds, key=lambda g: g.member_count, reverse=True)

        for i, guild in enumerate(sorted_guilds[:25]):  # Limit to 25 for embed limits
            owner = guild.owner
            embed.add_field(
                name=f"{i+1}. {guild.name}",
                value=f"ID: `{guild.id}`\nMembers: `{guild.member_count:,}`\nOwner: {owner.mention if owner else 'Unknown'}",
                inline=True,
            )

        if len(guilds) > 25:
            embed.set_footer(text=f"Showing 25 of {len(guilds)} guilds")

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="leave", description="Leave a guild (Owner only)")
    @app_commands.describe(guild_id="ID of the guild to leave")
    @app_commands.default_permissions(administrator=True)
    async def leave_guild(self, interaction: discord.Interaction, guild_id: str) -> None:
        """Make the bot leave a guild by ID."""
        try:
            guild_id_int = int(guild_id)
        except ValueError:
            await interaction.response.send_message("❌ Invalid guild ID.", ephemeral=True)
            return

        guild = self.bot.get_guild(guild_id_int)
        if not guild:
            await interaction.response.send_message("❌ Guild not found (bot may not be in it).", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            await guild.leave()
            await interaction.followup.send(f"✅ Left guild: **{guild.name}** (`{guild.id}`)")
            logger.info("Left guild: %s (%d)", guild.name, guild.id)
        except Exception as e:
            logger.exception("Failed to leave guild %d: %s", guild.id, e)
            await interaction.followup.send(f"❌ Failed to leave guild: {e}")

    @app_commands.command(name="status", description="Change bot activity status (Owner only)")
    @app_commands.describe(
        type="Activity type",
        name="Activity name/text",
        url="Streaming URL (required for streaming)"
    )
    @app_commands.choices(type=[
        app_commands.Choice(name="Playing", value="playing"),
        app_commands.Choice(name="Streaming", value="streaming"),
        app_commands.Choice(name="Listening", value="listening"),
        app_commands.Choice(name="Watching", value="watching"),
    ])
    @app_commands.default_permissions(administrator=True)
    async def set_status(
        self,
        interaction: discord.Interaction,
        type: app_commands.Choice[str],
        name: str,
        url: str = None
    ) -> None:
        """Change the bot's activity status."""
        activity_types = {
            "playing": discord.ActivityType.playing,
            "streaming": discord.ActivityType.streaming,
            "listening": discord.ActivityType.listening,
            "watching": discord.ActivityType.watching,
        }

        activity_type = activity_types[type.value]

        if type.value == "streaming" and not url:
            await interaction.response.send_message("❌ Streaming requires a URL.", ephemeral=True)
            return

        activity = discord.Activity(type=activity_type, name=name, url=url if type.value == "streaming" else None)

        await self.bot.change_presence(activity=activity)
        await interaction.response.send_message(
            f"✅ Status updated: **{type.value.capitalize()}** `{name}`" + (f" ({url})" if url else ""),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    """Set up the admin cog."""
    await bot.add_cog(AdminCog(bot))