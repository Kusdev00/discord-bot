import discord
import os
from dotenv import load_dotenv

load_dotenv('C:/Users/ojala/discord-bot/.env')
token = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.guilds = True
intents.message_content = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'Logged in as {client.user} (ID: {client.user.id})')
    
    guild = client.guilds[0]
    print(f'Guild: {guild.name}')
    
    # Find "important" category
    important_cat = discord.utils.get(guild.categories, name="important")
    if not important_cat:
        # Try case-insensitive
        for cat in guild.categories:
            if cat.name.lower() == "important":
                important_cat = cat
                break
    
    if not important_cat:
        print('Categories found:')
        for cat in guild.categories:
            print(f'  - {cat.name}')
        print('"important" category not found!')
        await client.close()
        return
    
    print(f'Found category: {important_cat.name}')
    
    # Check if channel already exists
    existing = discord.utils.get(important_cat.text_channels, name="server-info")
    if existing:
        channel = existing
        print(f'Channel #{channel.name} already exists')
    else:
        # Create permission overwrites - read only for everyone
        member_role = discord.utils.get(guild.roles, name="Member")
        if not member_role:
            # Try to find a default member role or use @everyone
            member_role = discord.utils.get(guild.roles, name="Member")
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                create_public_threads=False,
                create_private_threads=False,
                send_messages_in_threads=False
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                create_public_threads=True,
                create_private_threads=True,
                send_messages_in_threads=True
            )
        }
        
        # Add member role if exists
        if member_role:
            overwrites[member_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                create_public_threads=False,
                create_private_threads=False,
                send_messages_in_threads=False
            )
        
        channel = await guild.create_text_channel(
            name="server-info",
            category=important_cat,
            overwrites=overwrites,
            topic="Server information - read only"
        )
        print(f'Created channel: #{channel.name} in {important_cat.name}')
    
    # Send the embed
    embed = discord.Embed(
        title="🟢 Minecraft Server",
        description=(
            "**Server:**\n```\nestonianfemboys.falix.gg\n```"
            "**Version:** `1.21.11`"
        ),
        color=discord.Color.from_str("#2ecc71")
    )
    embed.set_image(url="https://cdn.discordapp.com/attachments/1510712073196142702/1522224684215701504/PDiX5y9uwlJ8.gif?ex=6a47b1b6&is=6a466036&hm=65841b3b4ce37f3949637f9e51a011572af13fd0c5ffc505b476af47df4392d0")
    embed.add_field(
        name="🔌 Plugins",
        value="• `/tpa` — Teleport to players\n• `/sethome` / `/home` — Set & teleport to homes\n• `VeinMiner` — Mine entire ore veins",
        inline=False
    )
    embed.add_field(
        name="⚙️ Core",
        value="PaperMC (optimized)",
        inline=True
    )
    embed.set_footer(text="tuff tuff • Server Info")
    
    try:
        await channel.send(embed=embed)
        print(f'Sent server info embed to #{channel.name}')
    except Exception as e:
        print(f'Error sending: {e}')
    
    await client.close()

client.run(token)