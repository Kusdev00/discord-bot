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
    
    # Find the #minecraft-info channel
    channel = discord.utils.get(guild.text_channels, name="minecraft-info")
    if not channel:
        print('#minecraft-info channel not found!')
        await client.close()
        return
    
    print(f'Found channel: #{channel.name}')
    
    # Fetch the last message from the bot in this channel
    messages = [msg async for msg in channel.history(limit=10)]
    bot_message = None
    for msg in messages:
        if msg.author == client.user and msg.embeds:
            bot_message = msg
            break
    
    if not bot_message:
        print('No bot message with embed found!')
        await client.close()
        return
    
    print(f'Found message ID: {bot_message.id}')
    
    # Create updated embed with FalixNodes link
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
    embed.add_field(
        name="🔄 Server Offline?",
        value="[Start the server on FalixNodes](https://falixnodes.net/startserver)",
        inline=False
    )
    embed.set_footer(text="tuff tuff • Server Info")
    
    try:
        await bot_message.edit(embed=embed)
        print(f'Updated message in #{channel.name}')
    except Exception as e:
        print(f'Error updating: {e}')
    
    await client.close()

client.run(token)