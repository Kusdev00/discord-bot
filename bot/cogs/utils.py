"""
Utility commands cog with helpful bot commands.
"""

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import Config
from bot.logging_config import get_logger

logger = get_logger(__name__)


class UtilsCog(commands.Cog):
    """Utility commands for the bot."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Check bot latency")
    async def ping(self, interaction: discord.Interaction) -> None:
        """Show bot latency."""
        latency = round(self.bot.latency * 1000)
        embed = discord.Embed(
            title="🏓 Pong!",
            description=f"Latency: **{latency}ms**",
            color=discord.Color.green() if latency < 200 else discord.Color.orange() if latency < 500 else discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="info", description="Show bot information")
    async def info(self, interaction: discord.Interaction) -> None:
        """Show bot information."""
        embed = discord.Embed(
            title="🤖 Bot Information",
            color=discord.Color.blurple(),
        )

        embed.add_field(name="🤖 Bot", value=f"{self.bot.user} (`{self.bot.user.id}`)", inline=False)
        embed.add_field(name="📊 Servers", value=f"`{len(self.bot.guilds):,}`", inline=True)
        embed.add_field(name="👥 Users", value=f"`{sum(g.member_count for g in self.bot.guilds):,}`", inline=True)
        embed.add_field(name="📡 Latency", value=f"`{round(self.bot.latency * 1000)}ms`", inline=True)
        embed.add_field(name="📦 discord.py", value=f"`{discord.__version__}`", inline=True)
        embed.add_field(name="🐍 Python", value=f"`{__import__('sys').version.split()[0]}`", inline=True)
        embed.add_field(name="⚙️ Prefix", value=f"`{Config.COMMAND_PREFIX}`", inline=True)

        if self.bot.user.avatar:
            embed.set_thumbnail(url=self.bot.user.avatar.url)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="serverinfo", description="Show server information")
    @app_commands.guild_only()
    async def serverinfo(self, interaction: discord.Interaction) -> None:
        """Show server information."""
        guild = interaction.guild

        embed = discord.Embed(
            title=f"📊 {guild.name} Info",
            color=discord.Color.blue(),
        )

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        # Basic info
        embed.add_field(name="🆔 Server ID", value=f"`{guild.id}`", inline=True)
        embed.add_field(name="👑 Owner", value=f"{guild.owner.mention if guild.owner else 'Unknown'}", inline=True)
        embed.add_field(name="📅 Created", value=f"<t:{int(guild.created_at.timestamp())}:F>", inline=True)

        # Member counts
        total = guild.member_count
        humans = sum(1 for m in guild.members if not m.bot)
        bots = total - humans
        embed.add_field(name="👥 Members", value=f"`{total:,}` total (`{humans:,}` humans, `{bots:,}` bots)", inline=True)

        # Channels
        text = len(guild.text_channels)
        voice = len(guild.voice_channels)
        categories = len(guild.categories)
        threads = len(guild.threads)
        embed.add_field(name="📝 Channels", value=f"`{text}` text, `{voice}` voice, `{categories}` categories, `{threads}` threads", inline=True)

        # Roles
        embed.add_field(name="🎭 Roles", value=f"`{len(guild.roles)}`", inline=True)

        # Features
        if guild.features:
            features = ", ".join(f"`{f}`" for f in guild.features[:10])
            embed.add_field(name="✨ Features", value=features, inline=False)

        if guild.banner:
            embed.set_image(url=guild.banner.url)

        embed.set_footer(text=f"Requested by {interaction.user}", icon_url=interaction.user.display_avatar.url)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="userinfo", description="Show user information")
    @app_commands.describe(user="The user to get info for (default: yourself)")
    @app_commands.guild_only()
    async def userinfo(self, interaction: discord.Interaction, user: discord.Member = None) -> None:
        """Show user information."""
        user = user or interaction.user

        embed = discord.Embed(
            title=f"👤 {user.display_name}",
            color=user.color if user.color != discord.Color.default() else discord.Color.blurple(),
        )

        embed.set_thumbnail(url=user.display_avatar.url)

        # Basic info
        embed.add_field(name="🆔 User ID", value=f"`{user.id}`", inline=True)
        embed.add_field(name="📛 Username", value=f"`{user.name}`", inline=True)
        embed.add_field(name="🏷️ Display Name", value=f"`{user.display_name}`", inline=True)

        # Dates
        embed.add_field(
            name="📅 Account Created",
            value=f"<t:{int(user.created_at.timestamp())}:F>\n(<t:{int(user.created_at.timestamp())}:R>)",
            inline=True,
        )
        embed.add_field(
            name="📥 Joined Server",
            value=f"<t:{int(user.joined_at.timestamp())}:F>\n(<t:{int(user.joined_at.timestamp())}:R>)" if user.joined_at else "Unknown",
            inline=True,
        )

        # Roles
        roles = [r.mention for r in sorted(user.roles[1:], key=lambda r: r.position, reverse=True)]
        if roles:
            roles_str = " ".join(roles[:20])
            if len(roles) > 20:
                roles_str += f" ... +{len(roles) - 20} more"
            embed.add_field(name=f"🎭 Roles ({len(roles)})", value=roles_str, inline=False)

        # Permissions
        key_perms = []
        if user.guild_permissions.administrator:
            key_perms.append("👑 Administrator")
        if user.guild_permissions.manage_guild:
            key_perms.append("⚙️ Manage Server")
        if user.guild_permissions.manage_channels:
            key_perms.append("📝 Manage Channels")
        if user.guild_permissions.manage_roles:
            key_perms.append("🎭 Manage Roles")
        if user.guild_permissions.ban_members:
            key_perms.append("🔨 Ban Members")
        if user.guild_permissions.kick_members:
            key_perms.append("👢 Kick Members")
        if user.guild_permissions.manage_messages:
            key_perms.append("🧹 Manage Messages")

        if key_perms:
            embed.add_field(name="🔑 Key Permissions", value="\n".join(key_perms), inline=True)

        embed.set_footer(text=f"Requested by {interaction.user}", icon_url=interaction.user.display_avatar.url)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="avatar", description="Get a user's avatar")
    @app_commands.describe(user="The user to get avatar for (default: yourself)")
    async def avatar(self, interaction: discord.Interaction, user: discord.User = None) -> None:
        """Get a user's avatar."""
        user = user or interaction.user

        embed = discord.Embed(
            title=f"🖼️ {user.display_name}'s Avatar",
            color=discord.Color.blurple(),
        )
        embed.set_image(url=user.display_avatar.url)
        embed.add_field(
            name="Links",
            value=f"[PNG]({user.display_avatar.with_format('png').url}) | [JPG]({user.display_avatar.with_format('jpg').url}) | [WEBP]({user.display_avatar.with_format('webp').url})",
            inline=False,
        )
        embed.set_footer(text=f"Requested by {interaction.user}", icon_url=interaction.user.display_avatar.url)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="help", description="Show available commands")
    async def help(self, interaction: discord.Interaction) -> None:
        """Show help with all available commands."""
        embed = discord.Embed(
            title="🤖 Bot Commands",
            description="All commands are slash commands. Use `/` to see autocomplete.",
            color=discord.Color.blurple(),
        )

        # Admin commands
        admin_cmds = [
            "`/welcome` - Configure welcome system",
            "`/status` - Change bot activity/status",
            "`/shutdown` - Shutdown bot (owner only)",
        ]
        embed.add_field(name="⚙️ Admin", value="\n".join(admin_cmds), inline=False)

        # Welcome subcommands
        welcome_cmds = [
            "`/welcome channel` - Set welcome channel",
            "`/welcome message_add` - Add welcome message",
            "`/welcome message_list` - List welcome messages",
            "`/welcome message_remove` - Remove welcome message",
            "`/welcome message_clear` - Clear custom messages",
            "`/welcome image_add` - Add welcome image",
            "`/welcome image_list` - List welcome images",
            "`/welcome image_remove` - Remove welcome image",
            "`/welcome image_clear` - Clear custom images",
            "`/welcome config` - Show welcome config",
            "`/welcome toggle` - Enable/disable welcome",
            "`/welcome color` - Set embed color",
            "`/welcome test` - Send test welcome",
            "`/welcome test_channel` - Set test channel",
            "`/welcome mention` - Toggle user mention",
        ]
        embed.add_field(name="🎉 Welcome", value="\n".join(welcome_cmds), inline=False)

        # Utility commands
        util_cmds = [
            "`/ping` - Check bot latency",
            "`/info` - Show bot info",
            "`/serverinfo` - Show server info",
            "`/userinfo` - Show user info",
            "`/avatar` - Get user avatar",
        ]
        embed.add_field(name="🛠️ Utility", value="\n".join(util_cmds), inline=False)

        embed.set_footer(text=f"Prefix: {Config.COMMAND_PREFIX} (prefix commands not implemented)")

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Set up the utils cog."""
    await bot.add_cog(UtilsCog(bot))