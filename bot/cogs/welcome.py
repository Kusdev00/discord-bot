"""
Welcome system cog with member join event handling and slash commands.
"""

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import Config
from bot.config.welcome_config import welcome_config
from bot.utils.embeds import (
    create_welcome_embed,
    create_welcome_config_embed,
    create_welcome_list_embed,
)
from bot.logging_config import get_logger

logger = get_logger(__name__)


class WelcomeCog(commands.Cog):
    """Welcome system with configurable messages, images, and embeds."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ==================== EVENT HANDLERS ====================

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Handle new member joining the server."""
        # Check if welcome system is enabled globally
        if not Config.WELCOME_ENABLED:
            return

        guild = member.guild

        # Load guild config
        config = welcome_config.load(guild.id)

        # Check if welcome is enabled for this guild
        if not config.get("enabled", True):
            return

        # Get welcome channel
        channel_id = config.get("channel_id")
        if not channel_id:
            logger.debug("No welcome channel set for guild %d", guild.id)
            return

        channel = guild.get_channel(channel_id)
        if not channel:
            logger.warning("Welcome channel %d not found in guild %d", channel_id, guild.id)
            return

        # Check bot permissions
        perms = channel.permissions_for(guild.me)
        if not perms.send_messages or not perms.embed_links:
            logger.warning("Missing permissions in welcome channel %d (guild %d)", channel_id, guild.id)
            return

        try:
            # Get random welcome message and image
            welcome_message = welcome_config.get_random_message(guild.id)
            image_url = welcome_config.get_random_image(guild.id)
            color = config.get("color", "random")
            mention_user = config.get("mention_user", True)

            # Create welcome embed
            embed = create_welcome_embed(
                member=member,
                guild=guild,
                welcome_message=welcome_message,
                image_url=image_url,
                color_setting=color,
            )

            # Send welcome message
            content = member.mention if mention_user else None
            sent_message = await channel.send(content=content, embed=embed)

            # Handle auto-delete if configured
            delete_after = config.get("delete_after")
            if delete_after:
                await sent_message.delete(delay=delete_after)

            logger.info("Sent welcome message for %s (%d) in guild %d", member, member.id, guild.id)

        except discord.Forbidden:
            logger.warning("Missing permissions to send welcome in %s (guild %d)", channel, guild.id)
        except discord.HTTPException as e:
            logger.exception("Failed to send welcome message: %s", e)

    # ==================== SLASH COMMANDS ====================

    welcome_group = app_commands.Group(name="welcome", description="Configure the welcome system", guild_only=True, default_permissions=discord.Permissions(manage_guild=True))

    @welcome_group.command(name="channel", description="Set the welcome channel")
    @app_commands.describe(channel="The channel to send welcome messages to")
    async def welcome_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        """Set the welcome channel for this server."""
        # Verify bot has permissions in the channel
        perms = channel.permissions_for(interaction.guild.me)
        if not perms.send_messages or not perms.embed_links:
            await interaction.response.send_message(
                f"❌ I don't have permission to send messages and embeds in {channel.mention}!",
                ephemeral=True,
            )
            return

        welcome_config.set(interaction.guild_id, "channel_id", channel.id)

        await interaction.response.send_message(
            f"✅ Welcome channel set to {channel.mention}",
            ephemeral=True,
        )

    @welcome_group.command(name="channel_remove", description="Remove the welcome channel (disables welcome)")
    async def welcome_channel_remove(self, interaction: discord.Interaction) -> None:
        """Remove the welcome channel."""
        welcome_config.set(interaction.guild_id, "channel_id", None)

        await interaction.response.send_message(
            "✅ Welcome channel removed. Welcome system disabled until a new channel is set.",
            ephemeral=True,
        )

    # --- Message subcommands ---
    @welcome_group.command(name="message_add", description="Add a custom welcome message")
    @app_commands.describe(
        message="The welcome message (supports {user_mention}, {user_name}, {server_name}, {server_member_count}, etc.)"
    )
    async def welcome_message_add(self, interaction: discord.Interaction, message: str) -> None:
        """Add a custom welcome message."""
        welcome_config.add_message(interaction.guild_id, message)

        await interaction.response.send_message(
            f"✅ Added welcome message:\n```\n{message}\n```",
            ephemeral=True,
        )

    @welcome_group.command(name="message_remove", description="Remove a custom welcome message by index")
    @app_commands.describe(index="The message number to remove (use /welcome message_list to see numbers)")
    async def welcome_message_remove(self, interaction: discord.Interaction, index: int) -> None:
        """Remove a custom welcome message by 1-based index."""
        # Convert to 0-based index
        if welcome_config.remove_message(interaction.guild_id, index - 1):
            await interaction.response.send_message(
                f"✅ Removed welcome message #{index}",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"❌ No message found at index #{index}. Use `/welcome message_list` to see available messages.",
                ephemeral=True,
            )

    @welcome_group.command(name="message_list", description="List all custom welcome messages")
    async def welcome_message_list(self, interaction: discord.Interaction) -> None:
        """List all custom welcome messages."""
        messages = welcome_config.get_messages(interaction.guild_id)
        embed = create_welcome_list_embed(
            title="💬 Custom Welcome Messages",
            items=messages,
            item_type="messages",
            guild=interaction.guild,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @welcome_group.command(name="message_clear", description="Clear all custom welcome messages (use defaults)")
    async def welcome_message_clear(self, interaction: discord.Interaction) -> None:
        """Clear all custom welcome messages."""
        welcome_config.clear_messages(interaction.guild_id)

        await interaction.response.send_message(
            "✅ Cleared all custom welcome messages. Default messages will be used.",
            ephemeral=True,
        )

    # --- Image subcommands ---
    @welcome_group.command(name="image_add", description="Add a custom welcome image (Discord CDN URL recommended)")
    @app_commands.describe(url="Direct link to an image (Discord CDN URL recommended)")
    async def welcome_image_add(self, interaction: discord.Interaction, url: str) -> None:
        """Add a custom welcome image URL."""
        # Basic URL validation
        if not url.startswith("http"):
            await interaction.response.send_message(
                "❌ Please provide a valid URL starting with http:// or https://",
                ephemeral=True,
            )
            return

        # Check if it's a Discord CDN URL (recommended)
        is_discord_cdn = "cdn.discordapp.com" in url or "media.discordapp.net" in url

        welcome_config.add_image(interaction.guild_id, url)

        await interaction.response.send_message(
            f"✅ Added welcome image{f' (Discord CDN ✓)' if is_discord_cdn else ''}:\n{url}",
            ephemeral=True,
        )

    @welcome_group.command(name="image_remove", description="Remove a custom welcome image by index")
    @app_commands.describe(index="The image number to remove (use /welcome image_list to see numbers)")
    async def welcome_image_remove(self, interaction: discord.Interaction, index: int) -> None:
        """Remove a custom welcome image by 1-based index."""
        if welcome_config.remove_image(interaction.guild_id, index - 1):
            await interaction.response.send_message(
                f"✅ Removed welcome image #{index}",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"❌ No image found at index #{index}. Use `/welcome image_list` to see available images.",
                ephemeral=True,
            )

    @welcome_group.command(name="image_list", description="List all custom welcome images")
    async def welcome_image_list(self, interaction: discord.Interaction) -> None:
        """List all custom welcome images."""
        images = welcome_config.get_images(interaction.guild_id)
        embed = create_welcome_list_embed(
            title="🖼️ Custom Welcome Images",
            items=images,
            item_type="images",
            guild=interaction.guild,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @welcome_group.command(name="image_bulk_add", description="Add multiple welcome images at once (space-separated URLs)")
    @app_commands.describe(urls="Space-separated image URLs (Discord CDN recommended)")
    async def welcome_image_bulk_add(self, interaction: discord.Interaction, urls: str) -> None:
        """Add multiple welcome images at once."""
        await interaction.response.defer(ephemeral=True)
        
        url_list = urls.split()
        if not url_list:
            await interaction.followup.send("❌ No URLs provided.", ephemeral=True)
            return
        
        added = 0
        failed = []
        for url in url_list:
            if not url.startswith("http"):
                failed.append(f"`{url}` - Invalid URL")
                continue
            
            try:
                welcome_config.add_image(interaction.guild_id, url)
                added += 1
            except Exception as e:
                failed.append(f"`{url}` - {e}")
        
        msg = f"✅ Added **{added}** images"
        if failed:
            msg += f"\n❌ Failed: {len(failed)}\n" + "\n".join(failed[:10])
            if len(failed) > 10:
                msg += f"\n... and {len(failed) - 10} more"
        
        await interaction.followup.send(msg, ephemeral=True)

    @welcome_group.command(name="image_import", description="Import welcome images from a channel's messages")
    @app_commands.describe(
        channel="Channel to scan for images",
        limit="Max messages to scan (default: 100)"
    )
    async def welcome_image_import(
        self, 
        interaction: discord.Interaction, 
        channel: discord.TextChannel,
        limit: int = 100
    ) -> None:
        """Import welcome images from a channel's message history."""
        await interaction.response.defer(ephemeral=True)
        
        # Check permissions
        perms = channel.permissions_for(interaction.guild.me)
        if not perms.read_message_history:
            await interaction.followup.send(f"❌ I don't have permission to read history in {channel.mention}", ephemeral=True)
            return
        
        added = 0
        urls_found = set()
        
        try:
            async for message in channel.history(limit=limit):
                # Check attachments
                for attachment in message.attachments:
                    if attachment.content_type and attachment.content_type.startswith("image/"):
                        urls_found.add(attachment.url)
                
                # Check embeds for images
                for embed in message.embeds:
                    if embed.image and embed.image.url:
                        urls_found.add(embed.image.url)
                    if embed.thumbnail and embed.thumbnail.url:
                        urls_found.add(embed.thumbnail.url)
                
                # Check message content for URLs
                import re
                url_pattern = re.compile(r'https?://[^\s]+')
                for match in url_pattern.finditer(message.content):
                    url = match.group()
                    # Only add if it looks like an image URL
                    if any(url.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp']):
                        urls_found.add(url)
                    elif 'cdn.discordapp.com' in url or 'media.discordapp.net' in url:
                        urls_found.add(url)
        
        except discord.Forbidden:
            await interaction.followup.send(f"❌ No permission to read {channel.mention}", ephemeral=True)
            return
        except Exception as e:
            logger.exception("Failed to import images from channel: %s", e)
            await interaction.followup.send(f"❌ Error scanning channel: {e}", ephemeral=True)
            return
        
        # Add found URLs
        for url in urls_found:
            try:
                welcome_config.add_image(interaction.guild_id, url)
                added += 1
            except Exception:
                pass
        
        await interaction.followup.send(
            f"✅ Scanned **{limit}** messages in {channel.mention}\n"
            f"Found **{len(urls_found)}** unique image URLs\n"
            f"Added **{added}** new images",
            ephemeral=True
        )

    @welcome_group.command(name="image_clear", description="Clear all custom welcome images")
    async def welcome_image_clear(self, interaction: discord.Interaction) -> None:
        """Clear all custom welcome images."""
        welcome_config.clear_images(interaction.guild_id)

        await interaction.response.send_message(
            "✅ Cleared all custom welcome images. Default images will be used.",
            ephemeral=True,
        )

    # --- Config subcommands ---
    @welcome_group.command(name="config", description="Show current welcome configuration")
    async def welcome_config_cmd(self, interaction: discord.Interaction) -> None:
        """Show current welcome configuration."""
        config = welcome_config.load(interaction.guild_id)
        embed = create_welcome_config_embed(interaction.guild, config)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @welcome_group.command(name="toggle", description="Enable or disable the welcome system")
    @app_commands.describe(state="Enable or disable welcome messages")
    @app_commands.choices(state=[
        app_commands.Choice(name="Enable", value="on"),
        app_commands.Choice(name="Disable", value="off"),
    ])
    async def welcome_toggle(self, interaction: discord.Interaction, state: app_commands.Choice[str]) -> None:
        """Enable or disable the welcome system for this server."""
        enabled = state.value == "on"
        welcome_config.set(interaction.guild_id, "enabled", enabled)

        await interaction.response.send_message(
            f"✅ Welcome system **{'enabled' if enabled else 'disabled'}** for this server.",
            ephemeral=True,
        )

    @welcome_group.command(name="color", description="Set the welcome embed color")
    @app_commands.describe(
        color="Color setting: random, or hex code like #ff6b6b, or named color (red, green, blue, yellow, purple, orange, pink, cyan)"
    )
    async def welcome_color(self, interaction: discord.Interaction, color: str) -> None:
        """Set the welcome embed color."""
        # Validate color
        valid_named = ["random", "red", "green", "blue", "yellow", "purple", "orange", "pink", "cyan"]
        color_lower = color.lower().strip()

        is_valid = False
        if color_lower in valid_named:
            is_valid = True
        elif color_lower.startswith("#") and len(color_lower) == 7:
            try:
                discord.Color.from_str(color_lower)
                is_valid = True
            except ValueError:
                pass

        if not is_valid:
            await interaction.response.send_message(
                f"❌ Invalid color. Use `random`, a hex code like `#ff6b6b`, or one of: {', '.join(valid_named)}",
                ephemeral=True,
            )
            return

        welcome_config.set(interaction.guild_id, "color", color_lower)

        await interaction.response.send_message(
            f"✅ Welcome embed color set to `{color_lower}`",
            ephemeral=True,
        )

    @welcome_group.command(name="test", description="Send a test welcome message to the test channel")
    async def welcome_test(self, interaction: discord.Interaction) -> None:
        """Send a test welcome message to the test channel."""
        config = welcome_config.load(interaction.guild_id)

        # Get test channel
        test_channel_id = config.get("test_channel_id") or Config.WELCOME_TEST_CHANNEL_ID
        if not test_channel_id:
            await interaction.response.send_message(
                "❌ No test channel configured. Set `WELCOME_TEST_CHANNEL_ID` in .env or use `/welcome test_channel`.",
                ephemeral=True,
            )
            return

        test_channel = interaction.guild.get_channel(test_channel_id)
        if not test_channel:
            await interaction.response.send_message(
                f"❌ Test channel not found (ID: {test_channel_id}).",
                ephemeral=True,
            )
            return

        # Check permissions
        perms = test_channel.permissions_for(interaction.guild.me)
        if not perms.send_messages or not perms.embed_links:
            await interaction.response.send_message(
                f"❌ I don't have permissions in {test_channel.mention}!",
                ephemeral=True,
            )
            return

        try:
            # Create test embed
            welcome_message = welcome_config.get_random_message(interaction.guild_id)
            image_url = welcome_config.get_random_image(interaction.guild_id)
            color = config.get("color", "random")

            embed = create_welcome_embed(
                member=interaction.user,  # Use command user as test member
                guild=interaction.guild,
                welcome_message=welcome_message,
                image_url=image_url,
                color_setting=color,
            )

            # Modify to indicate test
            embed.title = "🧪 **TEST** Welcome Message"
            embed.description = f"*This is a test message using your account*\n\n{embed.description}"
            embed.set_footer(text=f"TEST • {interaction.guild.name} • {interaction.guild.member_count:,} members")

            await test_channel.send(content=interaction.user.mention, embed=embed)

            await interaction.response.send_message(
                f"✅ Test welcome message sent to {test_channel.mention}",
                ephemeral=True,
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                f"❌ Missing permissions in {test_channel.mention}",
                ephemeral=True,
            )
        except discord.HTTPException as e:
            logger.exception("Failed to send test welcome: %s", e)
            await interaction.response.send_message(
                f"❌ Failed to send test message: {e}",
                ephemeral=True,
            )

    @welcome_group.command(name="test_channel", description="Set the test channel for welcome previews")
    @app_commands.describe(channel="The channel to send test welcome messages to")
    async def welcome_test_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        """Set the test channel for welcome previews."""
        perms = channel.permissions_for(interaction.guild.me)
        if not perms.send_messages or not perms.embed_links:
            await interaction.response.send_message(
                f"❌ I don't have permission to send messages and embeds in {channel.mention}!",
                ephemeral=True,
            )
            return

        welcome_config.set(interaction.guild_id, "test_channel_id", channel.id)

        await interaction.response.send_message(
            f"✅ Test channel set to {channel.mention}",
            ephemeral=True,
        )

    @welcome_group.command(name="mention", description="Toggle whether to mention the new user in welcome messages")
    @app_commands.describe(state="Enable or disable user mentions")
    @app_commands.choices(state=[
        app_commands.Choice(name="Enable", value="on"),
        app_commands.Choice(name="Disable", value="off"),
    ])
    async def welcome_mention(self, interaction: discord.Interaction, state: app_commands.Choice[str]) -> None:
        """Toggle user mentions in welcome messages."""
        enabled = state.value == "on"
        welcome_config.set(interaction.guild_id, "mention_user", enabled)

        await interaction.response.send_message(
            f"✅ User mentions in welcome messages **{'enabled' if enabled else 'disabled'}**",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    """Set up the welcome cog."""
    await bot.add_cog(WelcomeCog(bot))