"""
Invite blocking system with whitelist support.
"""

import re
import discord
from discord import app_commands
from discord.ext import commands

from bot.config import Config
from bot.logging_config import get_logger

logger = get_logger(__name__)

# Discord invite regex patterns
INVITE_PATTERNS = [
    re.compile(r"discord\.gg/[a-zA-Z0-9]+", re.IGNORECASE),
    re.compile(r"discord\.com/invite/[a-zA-Z0-9]+", re.IGNORECASE),
    re.compile(r"discordapp\.com/invite/[a-zA-Z0-9]+", re.IGNORECASE),
]

# Extract invite code from message
INVITE_CODE_PATTERN = re.compile(r"(?:discord\.gg|discord\.com/invite|discordapp\.com/invite)/([a-zA-Z0-9]+)", re.IGNORECASE)


class InviteBlockConfig:
    """Manages invite block configuration per guild using JSON."""

    def __init__(self):
        import json
        from pathlib import Path
        import sys
        PROJECT_ROOT = Path(__file__).parent.parent.parent
        sys.path.insert(0, str(PROJECT_ROOT))
        from config import Config as RootConfig
        self.config_dir = RootConfig.DATA_DIR / "inviteblock"
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def _get_config_path(self, guild_id: int):
        from pathlib import Path
        return self.config_dir / f"inviteblock_{guild_id}.json"

    def _get_default_config(self):
        return {
            "enabled": True,
            "whitelist": [],  # List of server IDs (strings)
            "log_channel_id": None,
            "delete_message": True,
            "warn_user": True,
            "punishment": "none",  # none, timeout, kick, ban
            "timeout_duration": 300,  # seconds
        }

    def load(self, guild_id: int):
        import json
        config_path = self._get_config_path(guild_id)
        if not config_path.exists():
            return self._get_default_config()
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            # Merge with defaults
            default = self._get_default_config()
            for k, v in default.items():
                if k not in config:
                    config[k] = v
            return config
        except Exception as e:
            logger.exception("Failed to load inviteblock config for %d: %s", guild_id, e)
            return self._get_default_config()

    def save(self, guild_id: int, config: dict):
        import json
        config_path = self._get_config_path(guild_id)
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.exception("Failed to save inviteblock config for %d: %s", guild_id, e)
            return False

    def get(self, guild_id: int, key: str, default=None):
        config = self.load(guild_id)
        return config.get(key, default)

    def set(self, guild_id: int, key: str, value):
        config = self.load(guild_id)
        config[key] = value
        return self.save(guild_id, config)

    def add_whitelist(self, guild_id: int, server_id: str):
        config = self.load(guild_id)
        if "whitelist" not in config:
            config["whitelist"] = []
        if server_id not in config["whitelist"]:
            config["whitelist"].append(server_id)
            return self.save(guild_id, config)
        return False

    def remove_whitelist(self, guild_id: int, server_id: str):
        config = self.load(guild_id)
        whitelist = config.get("whitelist", [])
        if server_id in whitelist:
            whitelist.remove(server_id)
            config["whitelist"] = whitelist
            return self.save(guild_id, config)
        return False

    def get_whitelist(self, guild_id: int):
        config = self.load(guild_id)
        return config.get("whitelist", [])

    def is_whitelisted(self, guild_id: int, server_id: str):
        whitelist = self.get_whitelist(guild_id)
        return str(server_id) in whitelist


inviteblock_config = InviteBlockConfig()


def extract_invites(text: str) -> list[str]:
    """Extract all Discord invite codes from text."""
    matches = INVITE_CODE_PATTERN.findall(text)
    return matches


async def resolve_invite(bot: commands.Bot, invite_code: str) -> discord.Invite | None:
    """Try to resolve an invite code to get the target guild ID."""
    try:
        invite = await bot.fetch_invite(invite_code)
        return invite
    except discord.NotFound:
        return None
    except discord.HTTPException:
        return None


class InviteBlockCog(commands.Cog):
    """Invite blocking with whitelist support."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bots, DMs, and users with manage_guild
        if message.author.bot or not message.guild:
            return
        if message.author.guild_permissions.manage_guild:
            return

        guild_id = message.guild.id
        config = inviteblock_config.load(guild_id)

        if not config.get("enabled", True):
            return

        # Check for invites
        invites = extract_invites(message.content)
        if not invites:
            return

        # Check each invite
        blocked = False
        whitelisted_servers = []
        blocked_invites = []

        for code in invites:
            invite = await resolve_invite(self.bot, code)
            if invite and invite.guild:
                target_guild_id = str(invite.guild.id)
                if inviteblock_config.is_whitelisted(guild_id, target_guild_id):
                    whitelisted_servers.append(f"{invite.guild.name} ({target_guild_id})")
                    continue
            # Unknown or non-whitelisted invite
            blocked = True
            blocked_invites.append(code)

        if not blocked:
            return

        # Take action
        if config.get("delete_message", True):
            try:
                await message.delete()
            except discord.Forbidden:
                pass

        # Warn user
        if config.get("warn_user", True):
            try:
                warning = (
                    f"❌ {message.author.mention}, sharing Discord invites is not allowed. "
                    f"Your message was removed."
                )
                if whitelisted_servers:
                    warning += f" Whitelisted servers mentioned: {', '.join(whitelisted_servers)}"
                await message.channel.send(warning, delete_after=10)
            except discord.Forbidden:
                pass

        # Punishment
        punishment = config.get("punishment", "none")
        if punishment != "none":
            try:
                if punishment == "timeout":
                    duration = config.get("timeout_duration", 300)
                    await message.author.timeout(
                        discord.utils.utcnow() + discord.timedelta(seconds=duration),
                        reason="Shared non-whitelisted Discord invite"
                    )
                elif punishment == "kick":
                    await message.author.kick(reason="Shared non-whitelisted Discord invite")
                elif punishment == "ban":
                    await message.author.ban(reason="Shared non-whitelisted Discord invite")
            except discord.Forbidden:
                pass

        # Log to test channel
        log_channel_id = config.get("log_channel_id") or Config.WELCOME_TEST_CHANNEL_ID
        if log_channel_id:
            log_channel = message.guild.get_channel(log_channel_id)
            if log_channel:
                try:
                    embed = discord.Embed(
                        title="🔒 Invite Blocked",
                        color=discord.Color.red(),
                        timestamp=discord.utils.utcnow()
                    )
                    embed.add_field(name="User", value=f"{message.author} ({message.author.id})", inline=True)
                    embed.add_field(name="Channel", value=message.channel.mention, inline=True)
                    embed.add_field(name="Blocked Invites", value="\n".join(f"discord.gg/{c}" for c in blocked_invites), inline=False)
                    if whitelisted_servers:
                        embed.add_field(name="Whitelisted Servers (allowed)", value="\n".join(whitelisted_servers), inline=False)
                    embed.add_field(name="Message", value=message.content[:1000], inline=False)
                    embed.set_footer(text=f"User ID: {message.author.id}")
                    await log_channel.send(embed=embed)
                except discord.Forbidden:
                    pass


# Slash commands for inviteblock
inviteblock_group = app_commands.Group(name="inviteblock", description="Configure invite blocking", guild_only=True, default_permissions=discord.Permissions(manage_guild=True))


@inviteblock_group.command(name="toggle", description="Enable or disable invite blocking")
@app_commands.describe(state="Enable or disable")
@app_commands.choices(state=[app_commands.Choice(name="Enable", value="on"), app_commands.Choice(name="Disable", value="off")])
async def inviteblock_toggle(interaction: discord.Interaction, state: app_commands.Choice[str]):
    enabled = state.value == "on"
    inviteblock_config.set(interaction.guild_id, "enabled", enabled)
    await interaction.response.send_message(f"✅ Invite blocking **{'enabled' if enabled else 'disabled'}**", ephemeral=True)


@inviteblock_group.command(name="whitelist_add", description="Add a server ID to the invite whitelist")
@app_commands.describe(server_id="Server ID to whitelist (e.g., your server ID)")
async def inviteblock_whitelist_add(interaction: discord.Interaction, server_id: str):
    if inviteblock_config.add_whitelist(interaction.guild_id, server_id):
        await interaction.response.send_message(f"✅ Added `{server_id}` to invite whitelist", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ `{server_id}` already whitelisted", ephemeral=True)


@inviteblock_group.command(name="whitelist_remove", description="Remove a server ID from the invite whitelist")
@app_commands.describe(server_id="Server ID to remove")
async def inviteblock_whitelist_remove(interaction: discord.Interaction, server_id: str):
    if inviteblock_config.remove_whitelist(interaction.guild_id, server_id):
        await interaction.response.send_message(f"✅ Removed `{server_id}` from invite whitelist", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ `{server_id}` not in whitelist", ephemeral=True)


@inviteblock_group.command(name="whitelist_list", description="List whitelisted server IDs")
async def inviteblock_whitelist_list(interaction: discord.Interaction):
    whitelist = inviteblock_config.get_whitelist(interaction.guild_id)
    if not whitelist:
        await interaction.response.send_message("📋 Whitelist is empty. Use `/inviteblock whitelist_add` to add server IDs.", ephemeral=True)
    else:
        embed = discord.Embed(title="📋 Invite Whitelist", color=discord.Color.blue())
        for sid in whitelist:
            embed.add_field(name=sid, value="Whitelisted", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


@inviteblock_group.command(name="config", description="Show current invite block configuration")
async def inviteblock_config_cmd(interaction: discord.Interaction):
    config = inviteblock_config.load(interaction.guild_id)
    embed = discord.Embed(title="🔒 Invite Block Configuration", color=discord.Color.blue())
    embed.add_field(name="Status", value="🟢 Enabled" if config.get("enabled") else "🔴 Disabled", inline=True)
    embed.add_field(name="Delete Message", value="✅ Yes" if config.get("delete_message") else "❌ No", inline=True)
    embed.add_field(name="Warn User", value="✅ Yes" if config.get("warn_user") else "❌ No", inline=True)
    embed.add_field(name="Punishment", value=config.get("punishment", "none"), inline=True)
    if config.get("punishment") == "timeout":
        embed.add_field(name="Timeout Duration", value=f"{config.get('timeout_duration', 300)}s", inline=True)
    whitelist = config.get("whitelist", [])
    embed.add_field(name="Whitelisted Servers", value=str(len(whitelist)), inline=True)
    log_channel_id = config.get("log_channel_id") or Config.WELCOME_TEST_CHANNEL_ID
    log_channel = interaction.guild.get_channel(log_channel_id)
    embed.add_field(name="Log Channel", value=log_channel.mention if log_channel else "`Not set`", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@inviteblock_group.command(name="delete_message", description="Toggle deleting messages with blocked invites")
@app_commands.choices(state=[app_commands.Choice(name="Enable", value="on"), app_commands.Choice(name="Disable", value="off")])
async def inviteblock_delete(interaction: discord.Interaction, state: app_commands.Choice[str]):
    enabled = state.value == "on"
    inviteblock_config.set(interaction.guild_id, "delete_message", enabled)
    await interaction.response.send_message(f"✅ Delete message: **{'enabled' if enabled else 'disabled'}**", ephemeral=True)


@inviteblock_group.command(name="warn_user", description="Toggle warning user when invite blocked")
@app_commands.choices(state=[app_commands.Choice(name="Enable", value="on"), app_commands.Choice(name="Disable", value="off")])
async def inviteblock_warn(interaction: discord.Interaction, state: app_commands.Choice[str]):
    enabled = state.value == "on"
    inviteblock_config.set(interaction.guild_id, "warn_user", enabled)
    await interaction.response.send_message(f"✅ Warn user: **{'enabled' if enabled else 'disabled'}**", ephemeral=True)


@inviteblock_group.command(name="punishment", description="Set punishment for sharing invites")
@app_commands.describe(type="Punishment type")
@app_commands.choices(type=[
    app_commands.Choice(name="None", value="none"),
    app_commands.Choice(name="Timeout", value="timeout"),
    app_commands.Choice(name="Kick", value="kick"),
    app_commands.Choice(name="Ban", value="ban"),
])
async def inviteblock_punishment(interaction: discord.Interaction, type: app_commands.Choice[str]):
    inviteblock_config.set(interaction.guild_id, "punishment", type.value)
    if type.value == "timeout":
        await interaction.response.send_message("✅ Punishment set to **timeout**. Use `/inviteblock timeout_duration` to set duration.", ephemeral=True)
    else:
        await interaction.response.send_message(f"✅ Punishment set to **{type.value}**", ephemeral=True)


@inviteblock_group.command(name="timeout_duration", description="Set timeout duration in seconds")
@app_commands.describe(seconds="Duration in seconds (default 300 = 5 minutes)")
async def inviteblock_timeout_duration(interaction: discord.Interaction, seconds: int):
    if seconds < 60 or seconds > 2419200:  # 1 min to 28 days
        await interaction.response.send_message("❌ Duration must be between 60 and 2,419,200 seconds (28 days)", ephemeral=True)
        return
    inviteblock_config.set(interaction.guild_id, "timeout_duration", seconds)
    await interaction.response.send_message(f"✅ Timeout duration set to **{seconds} seconds**", ephemeral=True)


@inviteblock_group.command(name="log_channel", description="Set log channel for blocked invites")
@app_commands.describe(channel="Channel to log blocked invites (default: test channel)")
async def inviteblock_log_channel(interaction: discord.Interaction, channel: discord.TextChannel = None):
    log_channel_id = channel.id if channel else None
    inviteblock_config.set(interaction.guild_id, "log_channel_id", log_channel_id)
    if channel:
        await interaction.response.send_message(f"✅ Log channel set to {channel.mention}", ephemeral=True)
    else:
        await interaction.response.send_message(f"✅ Log channel reset to default (test channel)", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(InviteBlockCog(bot))
    bot.tree.add_command(inviteblock_group)