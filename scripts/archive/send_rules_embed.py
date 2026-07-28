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
    
    # Target channel - using #general or #rules channel
    channel_id = 1509993402215694486  # #rules channel
    
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
    
    # Create similar styled embed
    embed = discord.Embed(
        title="⚠️ No Serious Drama in Main Channels",
        description=(
            "Keep serious drama, heated arguments, and personal conflicts out of the main channels. "
            "**Take it to DMs.** If staff asks you to move to DMs and you refuse, you risk getting muted.\n\n"
            "This is a chill hangout, not a courtroom. 🔥\n\n"
            "**📢 No Spreading Misinformation**\n"
            "Don't spread false or misleading information — whether about health, safety, important events, "
            "**or other people.** Spreading rumors, lies, or unfounded claims about members (doxxing, false accusations, etc.) "
            "will not be tolerated. Repeatedly sharing misinformation may result in a mute or ban."
        ),
        color=discord.Color.from_str("#e74c3c")
    )
    
    try:
        await channel.send(embed=embed)
        print(f'Sent embed to #{channel.name}')
    except Exception as e:
        print(f'Error sending: {e}')
    
    await client.close()

client.run(token)