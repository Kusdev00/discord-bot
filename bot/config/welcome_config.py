"""
Welcome system configuration management using JSON file storage.
"""

import json
import random
from pathlib import Path
from typing import Any, Optional
import sys
from pathlib import Path as PathLib

# Add project root to path for config import
PROJECT_ROOT = PathLib(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import Config
from bot.logging_config import get_logger

logger = get_logger(__name__)


class WelcomeConfig:
    """Manages welcome system configuration per guild using JSON files."""

    def __init__(self) -> None:
        self.config_dir = Config.WELCOME_CONFIG_DIR
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def _get_config_path(self, guild_id: int) -> Path:
        """Get the config file path for a guild."""
        return self.config_dir / f"welcome_{guild_id}.json"

    def _get_default_config(self) -> dict[str, Any]:
        """Get default welcome configuration."""
        return {
            "enabled": True,
            "channel_id": None,
            "test_channel_id": Config.WELCOME_TEST_CHANNEL_ID,
            "color": Config.WELCOME_DEFAULT_COLOR,
            "messages": [],
            "images": [],
            "mention_user": True,
            "delete_after": None,
        }

    def load(self, guild_id: int) -> dict[str, Any]:
        """Load welcome configuration for a guild."""
        config_path = self._get_config_path(guild_id)

        if not config_path.exists():
            logger.info("No welcome config found for guild %d, using defaults", guild_id)
            return self._get_default_config()

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            # Ensure all default keys exist (migration for new config options)
            default_config = self._get_default_config()
            for key, default_value in default_config.items():
                if key not in config:
                    config[key] = default_value

            logger.debug("Loaded welcome config for guild %d", guild_id)
            return config

        except (json.JSONDecodeError, OSError) as e:
            logger.exception("Failed to load welcome config for guild %d: %s", guild_id, e)
            return self._get_default_config()

    def save(self, guild_id: int, config: dict[str, Any]) -> bool:
        """Save welcome configuration for a guild."""
        config_path = self._get_config_path(guild_id)

        try:
            # Validate config has required keys
            default_config = self._get_default_config()
            for key in default_config:
                if key not in config:
                    config[key] = default_config[key]

            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

            logger.info("Saved welcome config for guild %d", guild_id)
            return True

        except OSError as e:
            logger.exception("Failed to save welcome config for guild %d: %s", guild_id, e)
            return False

    def get(self, guild_id: int, key: str, default: Any = None) -> Any:
        """Get a specific config value for a guild."""
        config = self.load(guild_id)
        return config.get(key, default)

    def set(self, guild_id: int, key: str, value: Any) -> bool:
        """Set a specific config value for a guild."""
        config = self.load(guild_id)
        config[key] = value
        return self.save(guild_id, config)

    # Message management
    def add_message(self, guild_id: int, message: str) -> bool:
        """Add a welcome message to the guild's config."""
        config = self.load(guild_id)
        if "messages" not in config:
            config["messages"] = []
        config["messages"].append(message)
        return self.save(guild_id, config)

    def remove_message(self, guild_id: int, index: int) -> bool:
        """Remove a welcome message by index (0-based)."""
        config = self.load(guild_id)
        messages = config.get("messages", [])
        if 0 <= index < len(messages):
            messages.pop(index)
            config["messages"] = messages
            return self.save(guild_id, config)
        return False

    def clear_messages(self, guild_id: int) -> bool:
        """Clear all custom welcome messages (will use defaults)."""
        config = self.load(guild_id)
        config["messages"] = []
        return self.save(guild_id, config)

    def get_messages(self, guild_id: int) -> list[str]:
        """Get all custom welcome messages for a guild."""
        config = self.load(guild_id)
        return config.get("messages", [])

    def get_random_message(self, guild_id: int) -> str:
        """Get a random welcome message (custom or default)."""
        from bot.utils.embeds import DEFAULT_WELCOME_MESSAGES

        config = self.load(guild_id)
        messages = config.get("messages", [])
        if messages:
            return random.choice(messages)
        return random.choice(DEFAULT_WELCOME_MESSAGES)

    # Image management
    def add_image(self, guild_id: int, image_url: str) -> bool:
        """Add a welcome image URL to the guild's config."""
        config = self.load(guild_id)
        if "images" not in config:
            config["images"] = []
        config["images"].append(image_url)
        return self.save(guild_id, config)

    def remove_image(self, guild_id: int, index: int) -> bool:
        """Remove a welcome image by index (0-based)."""
        config = self.load(guild_id)
        images = config.get("images", [])
        if 0 <= index < len(images):
            images.pop(index)
            config["images"] = images
            return self.save(guild_id, config)
        return False

    def clear_images(self, guild_id: int) -> bool:
        """Clear all custom welcome images."""
        config = self.load(guild_id)
        config["images"] = []
        return self.save(guild_id, config)

    def get_images(self, guild_id: int) -> list[str]:
        """Get all custom welcome images for a guild."""
        config = self.load(guild_id)
        return config.get("images", [])

    def get_random_image(self, guild_id: int) -> Optional[str]:
        """Get a random welcome image URL (custom or default)."""
        from bot.utils.embeds import DEFAULT_WELCOME_IMAGES

        config = self.load(guild_id)
        images = config.get("images", [])
        if images:
            return random.choice(images)
        return random.choice(DEFAULT_WELCOME_IMAGES) if DEFAULT_WELCOME_IMAGES else None


# Global config manager instance
welcome_config = WelcomeConfig()