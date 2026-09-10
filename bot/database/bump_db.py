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

        # Bump confirmations whose bumper could not be identified when the
        # message was processed (the cached interaction metadata is sometimes
        # empty). The repair loop re-fetches these messages - fresh fetches
        # reliably carry the invoking user - and moves them onto the waitlist.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bump_bumpers (
                message_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER,
                service TEXT NOT NULL,
                ping_at INTEGER NOT NULL,
                created_at INTEGER
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

    If the user is already queued for this service, the LATER ping time wins:
    a re-bump extends the reminder, and a late-attributed older confirmation
    can never shorten an existing cooldown.
    """
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO bump_waitlist (guild_id, user_id, service, ping_at, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (guild_id, user_id, service)
               DO UPDATE SET ping_at = MAX(ping_at, excluded.ping_at),
                            claim_expires_at = CASE
                                WHEN ping_at <> excluded.ping_at THEN NULL
                                ELSE claim_expires_at END,
                            created_at = excluded.created_at""",
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


# ==================== Pending bumpers (identity retry queue) ====================

async def add_pending_bumper(
    guild_id: int,
    message_id: int,
    service: str,
    ping_at: int,
    channel_id: Optional[int] = None,
) -> bool:
    """Queue a bump confirmation whose bumper couldn't be identified yet.

    The message id is the primary key and re-queueing is a no-op, so startup
    backfills can't reset the retry clock of an existing entry.
    """
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO bump_bumpers (message_id, guild_id, channel_id, service, ping_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (message_id) DO NOTHING""",
            (
                message_id,
                guild_id,
                channel_id,
                service,
                int(ping_at),
                int(datetime.now(timezone.utc).timestamp()),
            ),
        )
        await db.commit()
        return True
    except Exception as e:
        logger.exception("Failed to queue pending bumper for message %d: %s", message_id, e)
        return False
    finally:
        await db.close()


async def get_pending_bumpers() -> List[Dict[str, Any]]:
    """All pending-bumper rows, oldest first."""
    db = await get_db()
    try:
        async with db.execute(
            "SELECT * FROM bump_bumpers ORDER BY created_at ASC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    finally:
        await db.close()


async def resolve_pending_bumper(message_id: int) -> Optional[Dict[str, Any]]:
    """Pop a pending-bumper row once its identity was resolved.

    Returns the row (guild/service/ping_at for the waitlist insert) or None if
    it was already resolved by another pass.
    """
    db = await get_db()
    try:
        async with db.execute(
            "SELECT * FROM bump_bumpers WHERE message_id = ?", (message_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        await db.execute("DELETE FROM bump_bumpers WHERE message_id = ?", (message_id,))
        await db.commit()
        return dict(row)
    except Exception as e:
        logger.exception("Failed to resolve pending bumper for message %d: %s", message_id, e)
        return None
    finally:
        await db.close()


async def drop_pending_bumper(message_id: int) -> bool:
    """Give up on a pending-bumper row (expired without a resolvable identity)."""
    db = await get_db()
    try:
        await db.execute("DELETE FROM bump_bumpers WHERE message_id = ?", (message_id,))
        await db.commit()
        return True
    except Exception as e:
        logger.exception("Failed to drop pending bumper for message %d: %s", message_id, e)
        return False
    finally:
        await db.close()