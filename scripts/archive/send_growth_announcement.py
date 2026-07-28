"""
Simple personal announcement about motivation/mood.

Sends a brief, honest message to #random-logs.
"""

import discord
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv('C:/Users/ojala/discord-bot/.env')
token = os.getenv('DISCORD_TOKEN')

if not token:
    raise ValueError("DISCORD_TOKEN not found in .env file")

intents = discord.Intents.default()
intents.guilds = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    guild = client.guilds[0] if client.guilds else None
    if not guild:
        await client.close()
        return
    
    channel = guild.get_channel(1510712073196142702)
    if not channel:
        await client.close()
        return
    
    embed = discord.Embed(
        description=(
            "Hey everyone — just wanted to be real for a second. "
            "I've been struggling with motivation and mood lately, "
            "so I'm going to be taking a step back from actively "
            "trying to grow the server for a bit.\n\n"
            "Nothing dramatic, just need to focus on myself for now. "
            "The server isn't going anywhere, and I'll still be around. "
            "Just wanted you all to know."
        ),
        color=0x5865f2,  # Discord blurple
        timestamp=datetime.utcnow()
    )
    embed.set_author(
        name="Personal Update",
        icon_url=guild.me.display_avatar.url if guild.me.display_avatar else None
    )
    
    try:
        await channel.send(embed=embed)
        print(f"✅ Sent to #{channel.name}")
    except Exception as e:
        print(f"❌ Failed: {e}")
    
    await client.close()

client.run(token)