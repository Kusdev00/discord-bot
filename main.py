"""
Main entry point for the Discord bot.
"""

import sys
from bot.bot import bot
from config import Config
from bot.logging_config import get_logger

logger = get_logger(__name__)


def main() -> None:
    """Run the bot."""
    try:
        logger.info("Starting Discord bot...")
        bot.run(Config.DISCORD_TOKEN)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.exception("Bot crashed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()