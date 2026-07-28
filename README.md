# Discord Bot v2.0

A modular Discord bot built with discord.py featuring a customizable welcome system.

## Features

- **Welcome System**: Fully customizable welcome messages with embeds
  - Random welcome messages from configurable list
  - Random welcome images from Discord CDN URLs
  - Random or fixed embed colors
  - Rich embed with user info (username, display name, avatar, account creation date, member count)
  - Per-guild configuration stored in JSON
  - Slash commands for easy management
  - Test channel for previewing welcome messages

- **Modular Architecture**: Cog-based system for easy maintenance
- **Proper Logging**: Structured logging to console and file
- **Configuration**: Environment-based config with validation
- **Error Handling**: Graceful error handling for missing permissions, etc.

## Project Structure

```
discord-bot/
├── .env                    # Environment variables (copy from .env.example)
├── .env.example           # Example configuration
├── main.py                # Bot entry point
├── requirements.txt       # Python dependencies
├── pyproject.toml         # Project configuration
├── bot/
│   ├── __init__.py
│   ├── bot.py             # Main bot class
│   ├── config.py          # Configuration management
│   ├── logging_config.py  # Logging setup
│   ├── config/
│   │   ├── __init__.py
│   │   └── welcome_config.py  # Welcome system config (JSON storage)
│   ├── cogs/
│   │   ├── __init__.py
│   │   ├── welcome.py     # Welcome system cog
│   │   ├── admin.py       # Admin/management commands
│   │   └── utils.py       # Utility commands (userinfo, serverinfo, etc.)
│   └── utils/
│       ├── __init__.py
│       └── embeds.py      # Embed builders
├── data/
│   └── welcome/           # Per-guild welcome configs (JSON)
└── logs/                  # Bot logs
```

## Installation

1. **Clone the repository:**
   ```bash
   cd /c/Users/ojala/discord-bot
   ```

2. **Create virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env and add your DISCORD_TOKEN
   ```

5. **Run the bot:**
   ```bash
   python main.py
   ```

## Configuration

### Required Environment Variables

| Variable | Description |
|----------|-------------|
| `DISCORD_TOKEN` | Your Discord bot token from Developer Portal |

### Optional Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `COMMAND_PREFIX` | `!` | Prefix for text commands |
| `ACTIVITY_TYPE` | `playing` | Bot activity type (playing/streaming/listening/watching) |
| `ACTIVITY_NAME` | `with welcome system` | Activity display text |
| `TEST_GUILD_ID` | - | Guild ID for instant command sync in development |
| `WELCOME_ENABLED` | `true` | Enable/disable welcome system globally |
| `WELCOME_TEST_CHANNEL_ID` | - | Channel ID for `/welcome test` command |
| `WELCOME_DEFAULT_COLOR` | `random` | Default embed color (random, hex, or named color) |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG/INFO/WARNING/ERROR) |
| `LOG_FILE` | `logs/bot.log` | Log file path |
| `DEBUG` | `false` | Enable debug mode |

## Welcome System Commands

All welcome commands require **Manage Server** permission.

### Channel Management
| Command | Description |
|---------|-------------|
| `/welcome channel #channel` | Set welcome channel |
| `/welcome channel_remove` | Remove welcome channel |

### Message Management
| Command | Description |
|---------|-------------|
| `/welcome message_add "Welcome {user_mention}!"` | Add custom welcome message |
| `/welcome message_remove 1` | Remove message by index |
| `/welcome message_list` | List all custom messages |
| `/welcome message_clear` | Clear all custom messages |

### Image Management
| Command | Description |
|---------|-------------|
| `/welcome image_add https://cdn.discordapp.com/...` | Add welcome image URL |
| `/welcome image_remove 1` | Remove image by index |
| `/welcome image_list` | List all custom images |
| `/welcome image_clear` | Clear all custom images |

### Configuration
| Command | Description |
|---------|-------------|
| `/welcome config` | Show current configuration |
| `/welcome toggle on/off` | Enable/disable welcome system |
| `/welcome color random` | Set embed color (random, #hex, or named color) |
| `/welcome test` | Send test welcome to test channel |
| `/welcome test_channel #channel` | Set test channel |
| `/welcome mention on/off` | Toggle user mention |
| `/welcome delete_after 30` | Auto-delete after N seconds (0 to disable) |

### Message Placeholders

Custom welcome messages support these placeholders:

| Placeholder | Description |
|-------------|-------------|
| `{user_mention}` | Mentions the user (@user) |
| `{user_name}` | Username (e.g., `user#1234`) |
| `{user_display_name}` | Server display name |
| `{user_id}` | User ID |
| `{user_avatar_url}` | User avatar URL |
| `{user_created_at}` | Account creation date (formatted) |
| `{user_created_relative}` | Relative time (e.g., "2 years ago") |
| `{server_name}` | Server name |
| `{server_id}` | Server ID |
| `{server_member_count}` | Current member count |
| `{server_icon_url}` | Server icon URL |

**Example:** `Welcome {user_mention} to **{server_name}**! You're member #{server_member_count}!`

## Admin Commands

Require **Administrator** permission.

| Command | Description |
|---------|-------------|
| `/ping` | Check bot latency |
| `/sync [guild_only]` | Sync slash commands |
| `/reload <cog>` | Reload a cog (welcome/admin/utils) |
| `/load <cog>` | Load a cog |
| `/unload <cog>` | Unload a cog |
| `/cogs` | List loaded cogs |
| `/guilds` | List all guilds |
| `/leave <guild_id>` | Leave a guild |
| `/status <type> <name> [url]` | Change bot activity |
| `/shutdown` | Shutdown bot |

## Utility Commands

Available to all users.

| Command | Description |
|---------|-------------|
| `/ping` | Check bot latency |
| `/userinfo [user]` | Get user info |
| `/serverinfo` | Get server info |
| `/avatar [user]` | Get user avatar |
| `/banner [user]` | Get user banner |
| `/help` | Show all commands |

## Hosting Recommendations

### Best for Your Setup: Oracle Cloud (Already Have It)
You already run a Minecraft server on Oracle Cloud Always Free ARM instance. **Deploy the bot there too!**

**Advantages:**
- ✅ Already set up, no new accounts needed
- ✅ Always free (2 OCPU, 12GB RAM ARM)
- ✅ No sleep/wake cycles
- ✅ Full Linux control
- ✅ Low latency to Discord (choose Frankfurt/Amsterdam region)

**Quick Deploy on Oracle:**
```bash
# On your Oracle instance
git clone https://github.com/Kusdev00/discord-bot
cd discord-bot
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your token
# Run with systemd or Docker
```

### Alternative: Fly.io (Free Tier)
- No sleep, 256MB-1GB RAM
- Requires credit card for verification (not charged)
- `fly launch` → `fly deploy`

### Alternative: Koyeb (Free Tier)
- No credit card required
- No sleep
- GitHub integration

## Development

### Adding New Cogs
1. Create `bot/cogs/newfeature.py`
2. Add `async def setup(bot): await bot.add_cog(NewFeatureCog(bot))`
3. Add to `bot/cogs/__init__.py`
4. Load with `/reload newfeature` or restart bot

### Running Tests
```bash
pip install -e ".[dev]"
pytest
```

### Code Style
```bash
ruff check .
ruff format .
mypy bot/
```

## License

MIT License - Feel free to use and modify.