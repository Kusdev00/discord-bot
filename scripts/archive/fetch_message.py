"""
Fetch and display the message content to see what needs editing.
"""

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
    print(f'{client.user} connected')
    
    guild = client.guilds[0] if client.guilds else None
    if not guild:
        await client.close()
        return
    
    channel = guild.get_channel(1509993402215694486)
    if not channel:
        print(f"Channel not found")
        await client.close()
        return
    
    try:
        msg = await channel.fetch_message(1510016583752486913)
        print(f"=== MESSAGE CONTENT ===")
        print(repr(msg.content))
        print(f"=== EMBEDS ===")
        for i, embed in enumerate(msg.embeds):
            print(f"Embed {i}:")
            print(f"  title: {repr(embed.title)}")
            print(f"  description: {repr(embed.description)}")
            for field in embed.fields:
                print(f"  field: {field.name} = {repr(field.value)}")
            if embed.footer:
                print(f"  footer: {repr(embed.footer.text)}")
                
    except discord.NotFound:
        print("Message not found")
    except Exception as e:
        print(f"Error: {e}")
    
    await client.close()

client.run(token)