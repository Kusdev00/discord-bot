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
    
    # List all channels
    print('\nAll text channels:')
    for ch in guild.text_channels:
        cat = f" [{ch.category.name}]" if ch.category else " [No Category]"
        print(f'  #{ch.name}{cat} (ID: {ch.id})')
    
    await client.close()

client.run(token)