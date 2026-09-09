"""
Embed building utilities for the welcome system.
"""

import discord
import random
from datetime import datetime
from typing import Optional, List

# Default welcome messages (used when no custom messages configured)
DEFAULT_WELCOME_MESSAGES = [
    "Welcome to **{server_name}**, {user_mention}!",
    "Hey {user_mention}! Welcome aboard!",
    "A wild {user_mention} appeared! Welcome to **{server_name}**!",
    "Welcome {user_mention}! We're glad you're here!",
    "New member alert! {user_mention} joined **{server_name}**!",
    "Hello {user_mention}! Welcome to the family!",
    "Welcome to **{server_name}**, {user_mention}! Make yourself at home!",
    "Glad to see you, {user_mention}! Welcome to **{server_name}**!",
]

# Default welcome images (Discord CDN URLs - replace with your own)
DEFAULT_WELCOME_IMAGES = [
    # Add your Discord CDN URLs here
    # "https://cdn.discordapp.com/attachments/YOUR_CHANNEL_ID/IMAGE_ID/IMAGE_NAME.gif",
]


def format_welcome_message(
    template: str,
    member: discord.Member,
    guild: discord.Guild,
) -> str:
    """Format a welcome message template with member/server info."""
    # Account creation date
    created_at = member.created_at
    created_str = created_at.strftime("%B %d, %Y")
    created_relative = f"<t:{int(created_at.timestamp())}:R>"

    # Format the template
    return template.format(
        user_mention=member.mention,
        user_name=member.name,
        user_display_name=member.display_name,
        user_id=member.id,
        user_avatar_url=member.display_avatar.url,
        user_created_at=created_str,
        user_created_relative=created_relative,
        server_name=guild.name,
        server_id=guild.id,
        server_member_count=guild.member_count,
        server_icon_url=guild.icon.url if guild.icon else "",
    )


def get_random_color() -> discord.Color:
    """Get a random Discord embed color."""
    return discord.Color.from_rgb(
        random.randint(0, 255),
        random.randint(0, 255),
        random.randint(0, 255),
    )


def get_welcome_color(color_setting: str) -> discord.Color:
    """Get embed color based on configuration."""
    if color_setting.lower() == "random":
        return get_random_color()

    # Try parsing as hex
    try:
        return discord.Color.from_str(color_setting)
    except ValueError:
        # Fallback to random
        return get_random_color()


def create_welcome_embed(
    member: discord.Member,
    guild: discord.Guild,
    welcome_message: str,
    image_url: Optional[str] = None,
    color_setting: str = "random",
) -> discord.Embed:
    """Create a rich welcome embed for a new member."""
    # Format the welcome message
    formatted_message = format_welcome_message(welcome_message, member, guild)

    # Get embed color
    color = get_welcome_color(color_setting)

    # Account creation info
    created_at = member.created_at
    created_str = created_at.strftime("%B %d, %Y")
    created_relative = f"<t:{int(created_at.timestamp())}:R>"

    # Create embed
    embed = discord.Embed(
        description=formatted_message,
        color=color,
        timestamp=datetime.utcnow(),
    )

    # Author - user info
    embed.set_author(
        name=f"{member.name} (@{member.display_name})",
        icon_url=member.display_avatar.url,
    )

    # Thumbnail - user avatar
    embed.set_thumbnail(url=member.display_avatar.url)

    # Fields
    embed.add_field(
        name="👥 Member Count",
        value=f"**#{guild.member_count:,}**",
        inline=True,
    )

    # Footer
    embed.set_footer(
        text=f"{guild.name} • Welcome",
        icon_url=guild.icon.url if guild.icon else None,
    )

    # Image (if provided)
    if image_url:
        embed.set_image(url=image_url)

    return embed


def create_welcome_config_embed(
    guild: discord.Guild,
    config: dict,
) -> discord.Embed:
    """Create an embed showing current welcome configuration."""
    channel_id = config.get("channel_id")
    channel = guild.get_channel(channel_id) if channel_id else None

    embed = discord.Embed(
        title="🎉 Welcome System Configuration",
        description=f"Current settings for **{guild.name}**",
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow(),
    )

    # Channel
    embed.add_field(
        name="📍 Welcome Channel",
        value=channel.mention if channel else "`Not set`",
        inline=True,
    )

    # Enabled status
    enabled = config.get("enabled", True)
    embed.add_field(
        name="🔘 Status",
        value="🟢 Enabled" if enabled else "🔴 Disabled",
        inline=True,
    )

    # Color
    color_setting = config.get("color", "random")
    embed.add_field(
        name="🎨 Embed Color",
        value=f"`{color_setting}`",
        inline=True,
    )

    # Custom messages
    messages = config.get("messages", [])
    embed.add_field(
        name="💬 Custom Messages",
        value=f"**{len(messages)}** configured" if messages else "`Using defaults`",
        inline=True,
    )

    # Custom images
    images = config.get("images", [])
    embed.add_field(
        name="🖼️ Custom Images",
        value=f"**{len(images)}** configured" if images else "`Using defaults`",
        inline=True,
    )

    # Mention user
    mention_user = config.get("mention_user", True)
    embed.add_field(
        name="👤 Mention User",
        value="✅ Yes" if mention_user else "❌ No",
        inline=True,
    )

    # Test channel
    test_channel_id = config.get("test_channel_id")
    test_channel = guild.get_channel(test_channel_id) if test_channel_id else None
    embed.add_field(
        name="🧪 Test Channel",
        value=test_channel.mention if test_channel else "`Not set`",
        inline=True,
    )

    embed.set_footer(
        text=f"Guild ID: {guild.id}",
        icon_url=guild.icon.url if guild.icon else None,
    )

    return embed


def create_welcome_list_embed(
    title: str,
    items: List[str],
    item_type: str,
    guild: discord.Guild,
) -> discord.Embed:
    """Create an embed listing welcome messages or images."""
    embed = discord.Embed(
        title=f"{title} ({len(items)})",
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow(),
    )

    if not items:
        embed.description = f"No custom {item_type} configured. Using defaults."
    else:
        # Format items with numbers, guarding against Discord's 4096 character limit
        description = ""
        for i, item in enumerate(items, 1):
            if item_type == "images":
                # For images, show as clickable link with preview
                line = f"`{i}.` [Image {i}]({item})\n"
            else:
                # For messages, truncate long ones
                display = item[:100] + "..." if len(item) > 100 else item
                line = f"`{i}.` {display}\n"

            if len(description) + len(line) > 3900:
                remaining = len(items) - i + 1
                description += f"\n*...and {remaining} more {item_type} (Discord character limit reached)*"
                break

            description += line

        embed.description = description

    embed.set_footer(
        text=f"{guild.name} • Use /welcome {item_type} add/remove to manage",
        icon_url=guild.icon.url if guild.icon else None,
    )

    return embed


def create_test_welcome_embed(
    member: discord.Member,
    guild: discord.Guild,
    config: dict,
) -> discord.Embed:
    """Create a test welcome embed using the member as the 'new user'."""
    from bot.config.welcome_config import welcome_config

    welcome_message = welcome_config.get_random_message(guild.id)
    image_url = welcome_config.get_random_image(guild.id)
    color = config.get("color", "random")

    embed = create_welcome_embed(
        member=member,
        guild=guild,
        welcome_message=welcome_message,
        image_url=image_url,
        color_setting=color,
    )

    # Modify to indicate it's a test
    embed.title = "🧪 **TEST** Welcome Message"
    embed.description = f"*This is a preview using your account*\n\n{embed.description}"

    return embed