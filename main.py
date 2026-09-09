"""
Main entry point for the Discord bot.
"""

import sys
from bot.bot import bot
from config import Config
from bot.logging_config import get_logger, setup_logging

# Configure logging (console + logs/bot.log) BEFORE anything else logs.
# Without this, only discord.py's internal logger has a handler and every
# log line from our own code is silently dropped.
setup_logging()

logger = get_logger(__name__)


def main() -> None:
    """Run the bot."""
    try:
        logger.info("Starting Discord bot...")
        # log_handler=None: setup_logging() already attaches a console handler;
        # discord.py's default handler would duplicate every discord.* line.
        bot.run(Config.DISCORD_TOKEN, log_handler=None)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.exception("Bot crashed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()