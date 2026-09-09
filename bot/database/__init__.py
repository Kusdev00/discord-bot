"""
Database package initialization.
"""

from bot.database.bump_db import (
    init_db,
    get_guild_settings,
    update_guild_settings,
    get_notification_channel,
    is_guild_enabled,
    get_bump_state,
    record_successful_bump,
    mark_bump_message_seen,
    reset_bump_state,
    get_all_guild_bump_states,
    simulate_bump,
    check_duplicate_bump,
    add_to_waitlist,
    get_due_waitlist,
    claim_waitlist_entry,
    release_waitlist_entry,
    remove_from_waitlist,
    get_guild_waitlist,
    clear_guild_waitlist,
)

__all__ = [
    "init_db",
    "get_guild_settings",
    "update_guild_settings",
    "get_notification_channel",
    "is_guild_enabled",
    "get_bump_state",
    "record_successful_bump",
    "mark_bump_message_seen",
    "reset_bump_state",
    "get_all_guild_bump_states",
    "simulate_bump",
    "check_duplicate_bump",
    "add_to_waitlist",
    "get_due_waitlist",
    "claim_waitlist_entry",
    "release_waitlist_entry",
    "remove_from_waitlist",
    "get_guild_waitlist",
    "clear_guild_waitlist",
]