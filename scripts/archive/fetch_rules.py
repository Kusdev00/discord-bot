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
    
    # Fetch the specific message from #rules
    channel_id = 1509993402215694486  # #rules channel
    message_id = 1510731522603483247
    
    try:
        channel = client.get_channel(channel_id)
        if not channel:
            print(f'Channel {channel_id} not in cache, searching...')
            for guild in client.guilds:
                channel = guild.get_channel(channel_id)
                if channel:
                    break
        
        if channel:
            message = await channel.fetch_message(message_id)
            print(f'\n=== Message from {message.author} ===')
            print(f'Content: {message.content}')
            print(f'Embeds: {len(message.embeds)}')
            for i, embed in enumerate(message.embeds):
                print(f'\n--- Embed {i+1} ---')
                print(f'Title: {embed.title}')
                print(f'Description: {embed.description}')
                print(f'Color: {embed.color}')
                for field in embed.fields:
                    print(f'Field: {field.name} = {field.value}')
                if embed.footer:
                    print(f'Footer: {embed.footer.text}')
                if embed.author:
                    print(f'Author: {embed.author.name}')
        else:
            print('Channel not found')
    except Exception as e:
        print(f'Error: {e}')
    
    await client.close()

client.run(token)