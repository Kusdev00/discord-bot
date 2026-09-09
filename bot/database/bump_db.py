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

        # Per-person bump waitlist: everyone who successfully bumps is added
        # and personally pinged in the notification channel when their cooldown
        # (2h Disboard / 6h Carl-bot) expires, then removed.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bump_waitlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                service TEXT NOT NULL,
                ping_at INTEGER NOT NULL,
                claim_expires_at INTEGER,
                created_at INTEGER,
                UNIQUE (guild_id, user_id, service)
            )
        """)

        # Bump state per guild per service (timestamps stored as unix epoch seconds)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bump_state (
                guild_id INTEGER NOT NULL,
                service TEXT NOT NULL,
                last_successful_bump INTEGER,
                next_bump_available INTEGER,
                reminder_sent BOOLEAN DEFAULT FALSE,
                claim_expires_at INTEGER,
                last_processed_message_id INTEGER,
                updated_at INTEGER,
                PRIMARY KEY (guild_id, service)
            )
        """)

        # Upgrade tables created by older versions: CREATE TABLE IF NOT EXISTS
        # does not add columns to an existing table.
        try:
            await db.execute("ALTER TABLE bump_state ADD COLUMN claim_expires_at INTEGER")
            logger.info("Added claim_expires_at column to existing bump_state table")
        except Exception:
            logger.debug("claim_expires_at column already present")

        # Migration: convert legacy ISO-8601 timestamps to unix epoch seconds.
        # Python 3.9 sqlite can't compare mixed types, which made reminders fire
        # at the wrong time. Bump state rows are transient (per cooldown cycle)
        # so resetting them is safe.
        try:
            async with db.execute(
                "SELECT COUNT(*) FROM bump_state WHERE typeof(next_bump_available) = 'text'"
            ) as cursor:
                (legacy_count,) = await cursor.fetchone()
            if legacy_count:
                await db.execute("DELETE FROM bump_state WHERE typeof(next_bump_available) = 'text'")
                logger.info("Migrated %d legacy bump_state rows to epoch timestamps", legacy_count)
        except Exception as e:
            logger.warning("bump_state timestamp migration check failed: %s", e)

        # Recreate index if it was built against the legacy schema
        await db.execute("DROP INDEX IF EXISTS idx_bump_state_next_available")

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
    """Record a successful bump and update cooldown (epoch-second timestamps)."""
    # Import here to avoid circular imports
    from bot.config.bump_config import CARL_COOLDOWN, DISBOARD_COOLDOWN

    cooldown = CARL_COOLDOWN if service == "carl" else DISBOARD_COOLDOWN
    next_available = bump_time + cooldown

    db = await get_db()
    try:
        await db.execute(
            """INSERT OR REPLACE INTO bump_state
               (guild_id, service, last_successful_bump, next_bump_available, reminder_sent, claim_expires_at, last_processed_message_id, updated_at)
               VALUES (?, ?, ?, ?, FALSE, NULL, ?, ?)""",
            (
                guild_id,
                service,
                int(bump_time.timestamp()),
                int(next_available.timestamp()),
                message_id,
                int(datetime.now(timezone.utc).timestamp()),
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


async def claim_due_reminder(guild_id: int, service: str, hold_seconds: int = 300) -> bool:
    """Atomically claim a due reminder so concurrent schedulers can't double-send.

    Returns True if this call won the claim. The claim is stored as an epoch
    expiry and naturally releases (or can be re-claimed) once it lapses.
    """
    now = int(datetime.now(timezone.utc).timestamp())
    db = await get_db()
    try:
        await db.execute(
            """UPDATE bump_state
               SET claim_expires_at = ?, updated_at = ?
               WHERE guild_id = ?
                 AND service = ?
                 AND next_bump_available IS NOT NULL
                 AND next_bump_available <= ?
                 AND reminder_sent = FALSE
                 AND last_successful_bump IS NOT NULL
                 AND (claim_expires_at IS NULL OR claim_expires_at <= ?)""",
            (now + hold_seconds, now, guild_id, service, now, now),
        )
        await db.commit()
        return db.total_changes > 0
    except Exception as e:
        logger.exception("Failed to claim reminder: %s", e)
        return False
    finally:
        await db.close()


async def release_claim(guild_id: int, service: str) -> bool:
    """Release a previously claimed reminder so it can be retried later."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE bump_state SET claim_expires_at = NULL, updated_at = ? WHERE guild_id = ? AND service = ?",
            (int(datetime.now(timezone.utc).timestamp()), guild_id, service),
        )
        await db.commit()
        return True
    except Exception as e:
        logger.exception("Failed to release reminder claim: %s", e)
        return False
    finally:
        await db.close()


async def mark_reminder_sent(guild_id: int, service: str) -> bool:
    """Mark that the reminder has been sent for the current cycle."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE bump_state SET reminder_sent = 1, claim_expires_at = NULL, updated_at = ? WHERE guild_id = ? AND service = ?",
            (int(datetime.now(timezone.utc).timestamp()), guild_id, service),
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
        now = int(datetime.now(timezone.utc).timestamp())
        async with db.execute(
            """SELECT * FROM bump_state
               WHERE next_bump_available IS NOT NULL
               AND next_bump_available <= ?
               AND reminder_sent = FALSE
               AND last_successful_bump IS NOT NULL""",
            (now,),
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


async def set_next_bump_available(guild_id: int, service: str, epoch_seconds: int) -> bool:
    """Force a cooldown expiry time (unix epoch seconds). Used by test tooling
    to make a reminder due in seconds instead of the real 2h/6h cooldown."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE bump_state SET next_bump_available = ?, reminder_sent = 0, claim_expires_at = NULL, updated_at = ? WHERE guild_id = ? AND service = ?",
            (epoch_seconds, int(datetime.now(timezone.utc).timestamp()), guild_id, service),
        )
        await db.commit()
        return True
    except Exception as e:
        logger.exception("Failed to set next_bump_available: %s", e)
        return False
    finally:
        await db.close()


async def trigger_reminder_now(guild_id: int, service: str) -> bool:
    """Immediately trigger a reminder for testing (doesn't change real cooldown)."""
    # Get current state
    state = await get_bump_state(guild_id, service)
    if not state:
        return False

    # Temporarily set next_bump_available to now (epoch seconds)
    db = await get_db()
    try:
        now = int(datetime.now(timezone.utc).timestamp())
        await db.execute(
            "UPDATE bump_state SET next_bump_available = ?, reminder_sent = 0, updated_at = ? WHERE guild_id = ? AND service = ?",
            (
                now,
                now,
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


async def mark_bump_message_seen(guild_id: int, service: str, message_id: int) -> bool:
    """Mark a bump bot message as processed immediately.

    Bump bots may repost or edit their confirmation message; marking the id
    before any follow-up work prevents double-recording a bump.
    """
    db = await get_db()
    try:
        await db.execute(
            "UPDATE bump_state SET last_processed_message_id = ?, updated_at = ? WHERE guild_id = ? AND service = ?",
            (message_id, int(datetime.now(timezone.utc).timestamp()), guild_id, service),
        )
        await db.commit()
        return True
    except Exception as e:
        logger.exception("Failed to mark bump message seen: %s", e)
        return False
    finally:
        await db.close()


async def check_duplicate_bump(guild_id: int, service: str, message_id: int) -> bool:
    """Check if this message ID was already processed."""
    state = await get_bump_state(guild_id, service)
    if state and state.get("last_processed_message_id") == message_id:
        return True
    return False


# ==================== Bump Waitlist (per-person) ====================

async def add_to_waitlist(guild_id: int, user_id: int, service: str, ping_at: int) -> bool:
    """Add a bumper to the per-person waitlist.

    If the user is already queued for this service (e.g. two bump bot mirrors
    of the same bump), the newest cooldown wins.
    """
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO bump_waitlist (guild_id, user_id, service, ping_at, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (guild_id, user_id, service)
               DO UPDATE SET ping_at = excluded.ping_at, claim_expires_at = NULL, created_at = excluded.created_at""",
            (guild_id, user_id, service, int(ping_at), int(datetime.now(timezone.utc).timestamp())),
        )
        await db.commit()
        return True
    except Exception as e:
        logger.exception("Failed to add (%d, %d, %s) to bump waitlist: %s", guild_id, user_id, service, e)
        return False
    finally:
        await db.close()


async def get_due_waitlist() -> List[Dict[str, Any]]:
    """Get all waitlist entries whose ping time has arrived."""
    db = await get_db()
    try:
        now = int(datetime.now(timezone.utc).timestamp())
        async with db.execute(
            """SELECT * FROM bump_waitlist
               WHERE ping_at <= ?
                 AND (claim_expires_at IS NULL OR claim_expires_at <= ?)
               ORDER BY ping_at ASC""",
            (now, now),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    finally:
        await db.close()


async def claim_waitlist_entry(entry_id: int, hold_seconds: int = 300) -> bool:
    """Atomically claim a waitlist entry so concurrent scheduler passes can't
    double-ping. Returns True if this call won the claim."""
    now = int(datetime.now(timezone.utc).timestamp())
    db = await get_db()
    try:
        await db.execute(
            """UPDATE bump_waitlist SET claim_expires_at = ?
               WHERE id = ?
                 AND ping_at <= ?
                 AND (claim_expires_at IS NULL OR claim_expires_at <= ?)""",
            (now + hold_seconds, entry_id, now, now),
        )
        await db.commit()
        return db.total_changes > 0
    except Exception as e:
        logger.exception("Failed to claim waitlist entry %d: %s", entry_id, e)
        return False
    finally:
        await db.close()


async def release_waitlist_entry(entry_id: int) -> bool:
    """Release a claimed waitlist entry so the next pass retries it."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE bump_waitlist SET claim_expires_at = NULL WHERE id = ?",
            (entry_id,),
        )
        await db.commit()
        return True
    except Exception as e:
        logger.exception("Failed to release waitlist entry %d: %s", entry_id, e)
        return False
    finally:
        await db.close()


async def remove_from_waitlist(entry_id: int) -> bool:
    """Delete a waitlist entry after its ping was delivered."""
    db = await get_db()
    try:
        await db.execute("DELETE FROM bump_waitlist WHERE id = ?", (entry_id,))
        await db.commit()
        return True
    except Exception as e:
        logger.exception("Failed to remove waitlist entry %d: %s", entry_id, e)
        return False
    finally:
        await db.close()


async def get_guild_waitlist(guild_id: int) -> List[Dict[str, Any]]:
    """Get all waitlist entries for a guild (for status display)."""
    db = await get_db()
    try:
        async with db.execute(
            """SELECT * FROM bump_waitlist WHERE guild_id = ? ORDER BY ping_at ASC""",
            (guild_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    finally:
        await db.close()


async def clear_guild_waitlist(guild_id: int) -> int:
    """Delete all waitlist entries for a guild. Returns how many were removed."""
    db = await get_db()
    try:
        async with db.execute(
            "SELECT COUNT(*) AS c FROM bump_waitlist WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            (count,) = await cursor.fetchone()
        await db.execute("DELETE FROM bump_waitlist WHERE guild_id = ?", (guild_id,))
        await db.commit()
        return count
    except Exception as e:
        logger.exception("Failed to clear waitlist for guild %d: %s", guild_id, e)
        return 0
    finally:
        await db.close()