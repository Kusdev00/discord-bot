"""
Edit the rules embed to remove 'without permission.' from Rule 3.
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
        
        if not msg.embeds:
            print("No embeds found")
            await client.close()
            return
        
        embed = msg.embeds[0]
        
        # Create new embed with modified Rule 3
        new_embed = discord.Embed(
            title=embed.title,
            description=embed.description,
            color=embed.color
        )
        
        for field in embed.fields:
            value = field.value
            if "without permission" in value:
                value = value.replace("without permission.", "").replace("without permission", "")
                value = value.strip()
            new_embed.add_field(name=field.name, value=value, inline=field.inline)
        
        if embed.footer:
            new_embed.set_footer(text=embed.footer.text, icon_url=embed.footer.icon_url)
        if embed.thumbnail:
            new_embed.set_thumbnail(url=embed.thumbnail.url)
        if embed.image:
            new_embed.set_image(url=embed.image.url)
        
        await msg.edit(embed=new_embed)
        print(f"✅ Embed edited successfully")
        print(f"Modified Rule 3 value:")
        
    except discord.NotFound:
        print("Message not found")
    except discord.Forbidden:
        print("No permission to edit")
    except Exception as e:
        print(f"Error: {e}")
    
    await client.close()

client.run(token)