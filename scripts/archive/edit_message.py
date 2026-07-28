"""
Edit a specific message to remove 'without permission.' text.
"""

import discord
import os
from dotenv import load_dotenv

load_dotenv('C:/Users/ojala/discord-bot/.env')
token = os.getenv('DISCORD_TOKEN')

if not token:
    raise ValueError("DISCORD_TOKEN not found in .env file")

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
        print(f"Found message: {msg.content[:200]}...")
        
        new_content = msg.content.replace("without permission.", "").strip()
        
        if new_content == msg.content:
            print("'without permission.' not found in message")
        else:
            await msg.edit(content=new_content)
            print(f"✅ Message edited successfully")
            print(f"New content: {new_content[:200]}...")
            
    except discord.NotFound:
        print("Message not found")
    except discord.Forbidden:
        print("No permission to edit")
    except Exception as e:
        print(f"Error: {e}")
    
    await client.close()

client.run(token)