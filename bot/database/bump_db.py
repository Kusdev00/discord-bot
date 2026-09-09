"""
Bump system database layer - Python 3.9 compatible.
"""

import aiosqlite
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any
import sys

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import Config
from bot.logging_config import get_logger

logger = get_logger(__name__)

DB_PATH = Config.DATA_DIR / "bump.db"


async def get_db() -> aiosqlite.Connection:
    """Get a database connection with row factory."""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def init_db() -> None:
    """Initialize the database with required tables."""
    db = await get_db()
    try:
        # Bump settings per guild
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bump_settings (
                guild_id INTEGER PRIMARY KEY,
                enabled BOOLEAN DEFAULT TRUE,
                notification_channel_id INTEGER,
                mention_opted_in_users BOOLEAN DEFAULT TRUE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # User notification preferences per guild
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bump_users (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                notifications_enabled BOOLEAN DEFAULT TRUE,
                settings_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, user_id)
            )
        """)

        # Bump state per guild per service
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bump_state (
                guild_id INTEGER NOT NULL,
                service TEXT NOT NULL,
                last_successful_bump TIMESTAMP,
                next_bump_available TIMESTAMP,
                reminder_sent BOOLEAN DEFAULT FALSE,
                last_processed_message_id INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, service)
            )
        """)

        # Create indexes for efficient queries
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_bump_state_next_available
            ON bump_state (next_bump_available)
            WHERE next_bump_available IS NOT NULL AND reminder_sent = FALSE
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_bump_users_enabled
            ON bump_users (guild_id, notifications_enabled)
            WHERE notifications_enabled = TRUE
        """)

        await db.commit()
        logger.info("Bump database initialized")
    except Exception as e:
        logger.exception("Failed to initialize bump database: %s", e)
        raise
    finally:
        await db.close()


# ==================== Settings ====================

async def get_guild_settings(guild_id: int) -> Dict[str, Any]:
    """Get bump settings for a guild."""
    db = await get_db()
    try:
        async with db.execute(
            "SELECT * FROM bump_settings WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                d = dict(row)
                d["enabled"] = bool(d.get("enabled", 1))
                d["mention_opted_in_users"] = bool(d.get("mention_opted_in_users", 1))
                return d
            return {
                "guild_id": guild_id,
                "enabled": True,
                "notification_channel_id": None,
                "mention_opted_in_users": True,
            }
    finally:
        await db.close()


async def update_guild_settings(
    guild_id: int,
    enabled: Optional[bool] = None,
    notification_channel_id: Optional[int] = None,
    mention_opted_in_users: Optional[bool] = None,
) -> bool:
    """Update guild bump settings."""
    db = await get_db()
    try:
        settings = await get_guild_settings(guild_id)

        if enabled is not None:
            settings["enabled"] = enabled
        if notification_channel_id is not None:
            settings["notification_channel_id"] = notification_channel_id
        if mention_opted_in_users is not None:
            settings["mention_opted_in_users"] = mention_opted_in_users

        settings["updated_at"] = datetime.now(timezone.utc).isoformat()

        await db.execute(
            """INSERT OR REPLACE INTO bump_settings
               (guild_id, enabled, notification_channel_id, mention_opted_in_users, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                guild_id,
                1 if settings["enabled"] else 0,
                settings["notification_channel_id"],
                1 if settings["mention_opted_in_users"] else 0,
                settings["updated_at"],
            ),
        )
        await db.commit()
        return True
    except Exception as e:
        logger.exception("Failed to update guild settings: %s", e)
        return False
    finally:
        await db.close()


async def get_notification_channel(guild_id: int) -> Optional[int]:
    """Get the notification channel ID for a guild."""
    settings = await get_guild_settings(guild_id)
    return settings.get("notification_channel_id")


async def is_guild_enabled(guild_id: int) -> bool:
    """Check if bump system is enabled for a guild."""
    settings = await get_guild_settings(guild_id)
    return bool(settings.get("enabled", True))


async def should_mention_users(guild_id: int) -> bool:
    """Check if users should be mentioned in notifications."""
    settings = await get_guild_settings(guild_id)
    return bool(settings.get("mention_opted_in_users", True))


# ==================== User Preferences ====================

async def get_user_preference(guild_id: int, user_id: int) -> bool:
    """Get user's notification preference (defaults to True)."""
    db = await get_db()
    try:
        async with db.execute(
            "SELECT notifications_enabled FROM bump_users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ) as cursor:
            row = await cursor.fetchone()
            return bool(row["notifications_enabled"]) if row else True
    finally:
        await db.close()


async def set_user_preference(guild_id: int, user_id: int, enabled: bool) -> bool:
    """Set user's notification preference."""
    db = await get_db()
    try:
        await db.execute(
            """INSERT OR REPLACE INTO bump_users
               (guild_id, user_id, notifications_enabled, settings_updated_at)
               VALUES (?, ?, ?, ?)""",
            (guild_id, user_id, 1 if enabled else 0, datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()
        return True
    except Exception as e:
        logger.exception("Failed to set user preference: %s", e)
        return False
    finally:
        await db.close()


async def get_opted_in_users(guild_id: int) -> List[int]:
    """Get all user IDs with notifications enabled in a guild."""
    db = await get_db()
    try:
        async with db.execute(
            "SELECT user_id FROM bump_users WHERE guild_id = ? AND notifications_enabled = 1",
            (guild_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [row["user_id"] for row in rows]
    finally:
        await db.close()


async def get_user_preference_status(guild_id: int, user_id: int) -> Dict[str, Any]:
    """Get user's preference status for display."""
    db = await get_db()
    try:
        async with db.execute(
            "SELECT notifications_enabled, settings_updated_at FROM bump_users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                timestamp = row["settings_updated_at"]
                return {
                    "enabled": bool(row["notifications_enabled"]),
                    "updated_at": timestamp,
                    "settings_updated_at": timestamp,
                }
            return {
                "enabled": True,
                "updated_at": None,
                "settings_updated_at": None,
            }
    finally:
        await db.close()


async def count_opted_in_users(guild_id: int) -> int:
    """Count users with notifications enabled."""
    db = await get_db()
    try:
        async with db.execute(
            "SELECT COUNT(*) as count FROM bump_users WHERE guild_id = ? AND notifications_enabled = 1",
            (guild_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return row["count"] if row else 0
    finally:
        await db.close()


# ==================== Bump State ====================

async def get_bump_state(guild_id: int, service: str) -> Optional[Dict[str, Any]]:
    """Get bump state for a guild and service."""
    db = await get_db()
    try:
        async with db.execute(
            "SELECT * FROM bump_state WHERE guild_id = ? AND service = ?",
            (guild_id, service),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None
    finally:
        await db.close()


async def record_successful_bump(
    guild_id: int,
    service: str,
    bump_time: datetime,
    message_id: Optional[int] = None,
) -> bool:
    """Record a successful bump and update cooldown."""
    # Import here to avoid circular imports
    from bot.config.bump_config import CARL_COOLDOWN, DISBOARD_COOLDOWN

    cooldown = CARL_COOLDOWN if service == "carl" else DISBOARD_COOLDOWN
    next_available = bump_time + cooldown

    db = await get_db()
    try:
        await db.execute(
            """INSERT OR REPLACE INTO bump_state
               (guild_id, service, last_successful_bump, next_bump_available, reminder_sent, last_processed_message_id, updated_at)
               VALUES (?, ?, ?, ?, FALSE, ?, ?)""",
            (
                guild_id,
                service,
                bump_time.isoformat(),
                next_available.isoformat(),
                message_id,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()
        logger.info("Recorded successful %s bump for guild %d", service, guild_id)
        return True
    except Exception as e:
        logger.exception("Failed to record bump: %s", e)
        return False
    finally:
        await db.close()


async def mark_reminder_sent(guild_id: int, service: str) -> bool:
    """Mark that the reminder has been sent for the current cycle."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE bump_state SET reminder_sent = 1, updated_at = ? WHERE guild_id = ? AND service = ?",
            (datetime.now(timezone.utc).isoformat(), guild_id, service),
        )
        await db.commit()
        return True
    except Exception as e:
        logger.exception("Failed to mark reminder sent: %s", e)
        return False
    finally:
        await db.close()


async def reset_bump_state(guild_id: int, service: str) -> bool:
    """Reset bump state for a service (for testing)."""
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM bump_state WHERE guild_id = ? AND service = ?",
            (guild_id, service),
        )
        await db.commit()
        return True
    except Exception as e:
        logger.exception("Failed to reset bump state: %s", e)
        return False
    finally:
        await db.close()


async def get_all_pending_bumps() -> List[Dict[str, Any]]:
    """Get all bump states where cooldown has expired but reminder not sent."""
    db = await get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        async with db.execute(
            """SELECT * FROM bump_state
               WHERE next_bump_available IS NOT NULL
               AND next_bump_available <= ?
               AND reminder_sent = FALSE
               AND last_successful_bump IS NOT NULL""",
            (datetime.now(timezone.utc).isoformat(),),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_all_guild_bump_states(guild_id: int) -> Dict[str, Dict[str, Any]]:
    """Get all bump states for a guild."""
    db = await get_db()
    try:
        async with db.execute(
            "SELECT * FROM bump_state WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return {row["service"]: dict(row) for row in rows}
    finally:
        await db.close()


async def simulate_bump(guild_id: int, service: str) -> bool:
    """Simulate a successful bump for testing."""
    return await record_successful_bump(guild_id, service, datetime.now(timezone.utc))


async def trigger_reminder_now(guild_id: int, service: str) -> bool:
    """Immediately trigger a reminder for testing (doesn't change real cooldown)."""
    # Get current state
    state = await get_bump_state(guild_id, service)
    if not state:
        return False

    # Temporarily set next_bump_available to now
    db = await get_db()
    try:
        await db.execute(
            "UPDATE bump_state SET next_bump_available = ?, reminder_sent = 0, updated_at = ? WHERE guild_id = ? AND service = ?",
            (
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
                guild_id,
                service,
            ),
        )
        await db.commit()
        return True
    except Exception as e:
        logger.exception("Failed to trigger reminder: %s", e)
        return False
    finally:
        await db.close()


async def check_duplicate_bump(guild_id: int, service: str, message_id: int) -> bool:
    """Check if this message ID was already processed."""
    state = await get_bump_state(guild_id, service)
    if state and state.get("last_processed_message_id") == message_id:
        return True
    return False