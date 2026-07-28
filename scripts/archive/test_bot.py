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
    
    # Try to find the channel by ID
    channel = client.get_channel(1510712073196142702)
    
    if channel:
        print(f'Found channel: {channel.name} ({channel.id}) in {channel.guild.name}')
        try:
            await channel.send('🤖 Bot connection test successful! tuff tuff is online.')
            print('Test message sent successfully!')
        except Exception as e:
            print(f'Failed to send message: {e}')
    else:
        print('Channel not found in cache, searching all guilds...')
        for guild in client.guilds:
            for ch in guild.text_channels:
                if ch.id == 1510712073196142702:
                    print(f'Found channel: {ch.name} in {guild.name}')
                    try:
                        await ch.send('🤖 Bot connection test successful! tuff tuff is online.')
                        print('Test message sent successfully!')
                    except Exception as e:
                        print(f'Failed to send message: {e}')
                    break
    
    await client.close()

client.run(token)