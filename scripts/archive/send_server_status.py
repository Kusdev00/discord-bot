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
    
    channel_id = 1510712073196142702  # #random-logs
    
    channel = client.get_channel(channel_id)
    if not channel:
        for guild in client.guilds:
            channel = guild.get_channel(channel_id)
            if channel:
                break
    
    if not channel:
        print(f'Channel {channel_id} not found')
        await client.close()
        return
    
    # Create server info embed in same style
    embed = discord.Embed(
        title="🟢 Minecraft Server Online",
        description=(
            "**Server:** `estonianfemboys.falix.gg`\n"
            "**Version:** `1.21.11`\n"
            "**Status:** `Online` ✅"
        ),
        color=discord.Color.from_str("#2ecc71")  # Green for online
    )
    embed.add_field(
        name="📋 Connection Info",
        value="```\nestonianfemboys.falix.gg\nPort: 25565\n```",
        inline=False
    )
    embed.add_field(
        name="🎮 Features",
        value="• PaperMC (optimized)\n• Discord SRV linked\n• Cross-play ready",
        inline=True
    )
    embed.add_field(
        name="⚙️ Version",
        value="`1.21.11`\nLatest release",
        inline=True
    )
    embed.set_footer(text="tuff tuff • Server Monitor")
    
    try:
        await channel.send(embed=embed)
        print(f'Sent server status embed to #{channel.name}')
    except Exception as e:
        print(f'Error sending: {e}')
    
    await client.close()

client.run(token)