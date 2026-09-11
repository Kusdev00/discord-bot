"""
Bump notification system cog - Python 3.9 compatible.
"""

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Union

import discord
from discord import app_commands
from discord.ext import commands

from bot.config.bump_config import (
    BUMP_IDENTITY_RETRY_DELAY,
    BUMP_IDENTITY_RETRY_LIMIT,
    BUMP_RECENT_SCAN_LIMIT,
    CARL_BOT_ID,
    CARL_COOLDOWN,
    DISBOARD_BOT_ID,
    DISBOARD_COOLDOWN,
)
from bot.database import (
    add_to_waitlist,
    check_duplicate_bump,
    clear_guild_waitlist,
    get_all_guild_bump_states,
    get_bump_state,
    get_guild_settings,
    get_guild_waitlist,
    init_db,
    is_guild_enabled,
    mark_bump_message_seen,
    record_successful_bump,
    reset_bump_state,
    update_guild_settings,
    add_pending_bumper,
    drop_pending_bumper,
    get_pending_bumpers,
    resolve_pending_bumper,
)
from bot.logging_config import get_logger
from bot.services.bump_detector import debug_bump_detection, detect_bump
from bot.services.bump_notifier import BumpScheduler
from config import Config

logger = get_logger(__name__)


class BumpCog(commands.Cog):
    """Bump notification system."""

    # Command groups
    bump_notification_group = app_commands.Group(
        name="bumpnotification",
        description="Manage your bump notifications",
        guild_only=True,
    )

    bump_config_group = app_commands.Group(
        name="bumpconfig",
        description="Configure the bump system",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    bump_test_group = app_commands.Group(
        name="bumptest",
        description="Test bump system (admin only)",
        guild_only=True,
        default_permissions=discord.Permissions(administrator=True),
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.scheduler: Optional[BumpScheduler] = None
        self._backfill_task: Optional[asyncio.Task] = None
        self._identity_retry_task: Optional[asyncio.Task] = None
        # Per-guild ids of bump-bot messages the periodic scan has already
        # looked at; primed by the startup backfill so only genuinely new
        # confirmations get processed.
        self._seen_confirmation_ids: dict = {}

    async def cog_load(self) -> None:
        """Initialize database and start scheduler when cog loads."""
        await init_db()
        self.scheduler = BumpScheduler(self.bot)
        await self.scheduler.start()
        # Discord does not replay messages missed while we were down, so a
        # bump confirmed during a restart would be lost forever. Re-scan the
        # notification channel once we're connected.
        self._backfill_task = asyncio.create_task(self._backfill_recent_bumps())
        # Bump confirmations whose bumper couldn't be identified from the
        # cached interaction metadata are retried on a loop until they expire.
        self._identity_retry_task = asyncio.create_task(self._identity_retry_loop())
        logger.info("Bump system database initialized and scheduler started")

    async def cog_unload(self) -> None:
        """Stop scheduler when cog unloads."""
        if self._backfill_task:
            self._backfill_task.cancel()
        if self._identity_retry_task:
            self._identity_retry_task.cancel()
        if self.scheduler:
            await self.scheduler.stop()
        logger.info("Bump scheduler stopped")

    # ==================== EVENT HANDLERS ====================

    def _find_bumper(self, message: discord.Message) -> Optional[Union[discord.Member, discord.User]]:
        """Find the user who performed the bump from interaction or mentions."""
        # 1. Check interaction metadata (slash command user)
        if hasattr(message, "interaction_metadata") and message.interaction_metadata:
            user = getattr(message.interaction_metadata, "user", None)
            if user:
                return user

        # 1b. APP messages: message.interaction is deprecated/absent for newer
        # interaction responses; application_id may carry the application (not
        # the user). Nothing more to extract from those here - logged for
        # diagnosis in on_message instead.

        # 2. Check interaction attribute
        if hasattr(message, "interaction") and message.interaction:
            user = getattr(message.interaction, "user", None)
            if user:
                return user

        # 3. Check for user mention in embeds (e.g. Disboard starts with <@123456>, bump done!)
        for embed in message.embeds:
            texts = [embed.title, embed.description]
            if embed.fields:
                texts.extend(field.value for field in embed.fields)
            for text in texts:
                if not text:
                    continue
                match = re.search(r"<@!?(\d+)>", text)
                if match:
                    user_id = int(match.group(1))
                    if user_id not in (CARL_BOT_ID, DISBOARD_BOT_ID):
                        member = message.guild.get_member(user_id) if message.guild else None
                        return member or self.bot.get_user(user_id)

        # 4. Check for user mention in plain text content
        if message.content:
            match = re.search(r"<@!?(\d+)>", message.content)
            if match:
                user_id = int(match.group(1))
                if user_id not in (CARL_BOT_ID, DISBOARD_BOT_ID):
                    member = message.guild.get_member(user_id) if message.guild else None
                    return member or self.bot.get_user(user_id)

        # 5. Carl-bot's successful bump is a reply to the "user used /bump"
        # marker message, which carries the invoking user in its interaction
        # metadata. Walk the reply chain until we find a usable identity.
        reference = message.reference
        if reference:
            resolved = reference.resolved
            if isinstance(resolved, discord.Message):
                # Direct marker: a real user authored it.
                if not resolved.author.bot:
                    return resolved.author
                # Otherwise the marker itself is a bot message (less common)
                # but still carries interaction_metadata.
                meta = getattr(resolved, "interaction_metadata", None)
                if meta is not None:
                    user = getattr(meta, "user", None)
                    if user is not None:
                        return user
                # Fallback: some bots attach an 'interaction' object at the top
                # level.
                interaction = getattr(resolved, "interaction", None)
                if interaction is not None:
                    user = getattr(interaction, "user", None)
                    if user is not None:
                        return user

        # 6. We didn't find a usable identity from the cached reference.
        # returned None + has a reference => let the caller async-fetch the
        # marker message via _resolve_bumper_from_reference() below.
        return None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Listen for successful bumps from Carl-bot and Disboard."""
        # Tracer: log EVERY message from either bump bot, before any gate.
        # Volume is tiny (a few per day) and it proves whether the gateway
        # actually delivered the event to us - no log here means the event
        # never arrived, not that detection failed.
        if message.author.id in (CARL_BOT_ID, DISBOARD_BOT_ID) or message.application_id in (
            CARL_BOT_ID,
            DISBOARD_BOT_ID,
        ):
            logger.info(
                "Bump TRACE: msg from author %d app %s in channel %d (guild=%s) content=%r",
                message.author.id,
                message.application_id,
                message.channel.id if message.channel else -1,
                message.guild.id if message.guild else None,
                (message.content or "")[:80],
            )

        if not message.guild:
            return

        # Only process messages from Carl-bot or Disboard. APP messages
        # (slash-command interaction responses) are attributed via
        # message.application_id, which is checked too in case the author
        # object was hydrated as something other than the bot user.
        if message.author.id not in (CARL_BOT_ID, DISBOARD_BOT_ID) and message.application_id not in (
            CARL_BOT_ID,
            DISBOARD_BOT_ID,
        ):
            return

        # Check if bump system is enabled for this guild
        if not await is_guild_enabled(message.guild.id):
            return

        # Detect successful bump
        service = await detect_bump(message)
        if service:
            # Check for duplicate
            if await check_duplicate_bump(message.guild.id, service, message.id):
                logger.debug("Duplicate bump message ignored: %d", message.id)
                return

            # Skip confirmations at or before the last recorded bump for this
            # service: they were already counted (backfill re-visits old
            # messages, and re-adding them would resurrect stale cooldowns).
            state = await get_bump_state(message.guild.id, service)
            if state and state.get("last_successful_bump"):
                try:
                    last_ts = int(state["last_successful_bump"])
                except (TypeError, ValueError):
                    last_ts = None
                if last_ts and int(message.created_at.timestamp()) <= last_ts:
                    logger.info(
                        "Ignored %s bump confirmation %d (at or before last recorded bump)",
                        service,
                        message.id,
                    )
                    return

            # The bump happened when the confirmation was posted - not "now".
            # Equal for live messages; correct for backfilled ones after a
            # restart, so cooldowns are dated from the real bump time.
            bump_time = message.created_at or datetime.now(timezone.utc)

            # Disboard's cooldown is SERVER-WIDE: only one bump per 2 hours.
            # Discord mirrors its confirmation across channels, so a second copy
            # can arrive as a NEW message id minutes later - ignore anything
            # inside the active cooldown. (Carl-bot is per-user, so its state
            # must never gate new bumpers - anyone may /bump at any time.)
            if service == "disboard":
                state = await get_bump_state(message.guild.id, service)
                if state and state.get("next_bump_available"):
                    try:
                        next_available = int(state["next_bump_available"])
                    except (TypeError, ValueError):
                        next_available = None
                    if next_available and next_available > int(bump_time.timestamp()) - 1:
                        logger.info(
                            "Ignored extra %s bump confirmation in guild %d (service on cooldown)",
                            service,
                            message.guild.id,
                        )
                        return

            # Record the server-level state (used for status displays and the
            # Disboard cooldown guard) and mark the message seen so a repost or
            # edit of the confirmation can never double-count a bump.
            await record_successful_bump(message.guild.id, service, bump_time)
            await mark_bump_message_seen(message.guild.id, service, message.id)

            # Put the bumper on the personal waitlist: they get pinged in the
            # notification channel when THEIR cooldown (2h/6h) expires, then
            # removed from the list. Live confirmations always have an active
            # window; backfilled old ones may not - adding those would ping
            # days late, so only the state is recorded for them.
            cooldown = CARL_COOLDOWN if service == "carl" else DISBOARD_COOLDOWN
            ping_at = int((bump_time + cooldown).timestamp())
            window_active = ping_at > int(datetime.now(timezone.utc).timestamp())

            if Config.DEBUG:
                try:
                    logger.info(
                        "Bump DEBUG author_id=%d application_id=%s webhook_id=%s type=%s channel=%d content=%r embeds=%d",
                        message.author.id,
                        message.application_id,
                        message.webhook_id,
                        message.type,
                        message.channel.id,
                        (message.content or "")[:120],
                        len(message.embeds),
                    )
                except Exception:
                    logger.exception("Bump DEBUG dump failed")

            if not window_active:
                logger.info(
                    "Recorded %s bump in guild %d from %s but its cooldown window "
                    "already passed; not adding anyone to the waitlist",
                    service,
                    message.guild.id,
                    message.id,
                )
                return

            bumper = self._find_bumper(message)
            pathway = "cached reference"

            # If _find_bumper couldn't spot the user from the cached reference,
            # try fetching the marker message fresh and re-reading its interaction
            # metadata (Carl-bot replies usually carry a usable reference).
            if bumper is None and message.reference and message.reference.message_id:
                bumper = await self._resolve_bumper_from_reference(message)
                pathway = "fresh reference fetch"

            if bumper is None:
                if Config.DEBUG:
                    logger.info(
                        "Bump DEBUG bumper-identify failed: app_id=%s webhook_id=%s meta=%s interaction=%s ref=%s",
                        message.application_id,
                        message.webhook_id,
                        bool(getattr(message, "interaction_metadata", None)),
                        bool(getattr(message, "interaction", None)),
                        bool(message.reference),
                    )
                # The bump itself is recorded; only the identity is missing.
                # Queue the confirmation for the identity-retry loop, which
                # re-fetches the message until Discord serves the interaction
                # metadata or the retry window expires.
                await add_pending_bumper(
                    message.guild.id,
                    message.id,
                    service,
                    ping_at,
                    channel_id=message.channel.id,
                )
                logger.info(
                    "Recorded %s bump in guild %d but could not identify the bumper "
                    "(pathway=%s); queued for identity retry",
                    service,
                    message.guild.id,
                    pathway,
                )
            else:
                await add_to_waitlist(message.guild.id, bumper.id, service, ping_at)
                logger.info(
                    "Detected %s bump by %s (%d) in guild %d; ping due at %d "
                    "(pathway=%s)",
                    service,
                    bumper,
                    bumper.id,
                    message.guild.id,
                    ping_at,
                    pathway,
                )

        else:
            # A bump-related message we didn't classify. Log it so the bot's exact
            # wording can be added to the detection keywords if a real bump slips by.
            texts = [message.content or ""]
            for embed in message.embeds:
                texts.extend([embed.title or "", embed.description or ""])
                texts.extend(field.value or "" for field in embed.fields)
            combined = " ".join(texts)
            if "bump" in combined.lower():
                logger.info(
                    "Ignoring %s message mentioning bump without a success match: %s",
                    message.author,
                    " ".join(combined.split())[:200],
                )


    async def _identity_retry_loop(self) -> None:
        """Retry bumper identification for queued bump confirmations.

        Interaction metadata is sometimes missing from the cached message
        (and from the cached reply target), yet a FRESH fetch of the same
        message reliably carries it - the diagnostic command proves this
        regularly. Queued messages are re-fetched every pass until the
        identity resolves or the retry window expires.

        Each pass also re-scans the newest channel messages: a bump
        confirmation can reach us under-hydrated (blank content/embeds, so
        detection finds nothing) or not reach us at all (gateway hiccup
        without a disconnect). Fresh history fetches always carry the full
        text and interaction metadata, so the scan closes both gaps within
        one retry interval.
        """
        try:
            await self.bot.wait_until_ready()
            while True:
                try:
                    await self._repair_pending_bumpers()
                    await self._scan_recent_confirmations()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Bumper identity retry pass failed")
                await asyncio.sleep(BUMP_IDENTITY_RETRY_DELAY)
        except asyncio.CancelledError:
            pass

    async def _scan_recent_confirmations(self) -> None:
        """Repair newly-arrived confirmations that the live path missed.

        Runs every retry pass over the newest few channel messages. Anything
        already seen (live, startup backfill, or a previous pass) is skipped,
        so the cost is one small history fetch per guild per pass and each
        message is processed exactly once.
        """
        for guild in list(self.bot.guilds):
            try:
                if not await is_guild_enabled(guild.id):
                    continue
                settings = await get_guild_settings(guild.id)
                channel_id = settings.get("notification_channel_id")
                channel = guild.get_channel(channel_id) if channel_id else None
                if channel is None or not hasattr(channel, "history"):
                    continue

                seen = self._seen_confirmation_ids.setdefault(guild.id, set())
                repaired = 0
                async for msg in channel.history(limit=BUMP_RECENT_SCAN_LIMIT):
                    if msg.author.id not in (CARL_BOT_ID, DISBOARD_BOT_ID) and msg.application_id not in (
                        CARL_BOT_ID,
                        DISBOARD_BOT_ID,
                    ):
                        continue
                    if msg.id in seen:
                        continue
                    seen.add(msg.id)
                    if await self._repair_backfill_message(msg):
                        repaired += 1
                if repaired:
                    logger.info(
                        "Bump scan: repaired %d missed confirmation(s) in guild %d",
                        repaired,
                        guild.id,
                    )
            except Exception:
                logger.exception("Bump recent-confirmation scan failed for guild %s", guild.id)

    async def _repair_pending_bumpers(self) -> None:
        """Resolve queued confirmations and move them onto the waitlist."""
        pending = await get_pending_bumpers()
        if not pending:
            return

        now = int(datetime.now(timezone.utc).timestamp())
        for row in pending:
            created = int(row.get("created_at") or 0)
            window_expired = created and now - created > BUMP_IDENTITY_RETRY_LIMIT
            if window_expired:
                await drop_pending_bumper(row["message_id"])
                logger.warning(
                    "Gave up identifying the bumper for %s confirmation %d in guild %d "
                    "after %d days; nobody added to the waitlist",
                    row["service"],
                    row["message_id"],
                    row["guild_id"],
                    BUMP_IDENTITY_RETRY_LIMIT // 86400,
                )
                continue

            message = await self._fetch_message_anywhere(
                row["message_id"], row.get("channel_id"), row.get("guild_id")
            )
            if message is None:
                continue

            bumper = self._find_bumper(message)
            if bumper is None:
                bumper = await self._resolve_bumper_from_reference(message)

            if bumper is None:
                continue

            entry = await resolve_pending_bumper(row["message_id"])
            if entry is None:
                continue

            # Guard against stale reminders: if a bump for this service was
            # recorded at/after this confirmation's cooldown expiry, this
            # cooldown cycle has already been superseded - its reminder was
            # either delivered (as a newer bump's ping) or deliberately reset.
            # A late row must never resurrect a ping that already happened.
            state = await get_bump_state(entry["guild_id"], entry["service"])
            last = int(state["last_successful_bump"]) if state and state.get("last_successful_bump") else None
            if last is not None and last >= int(entry["ping_at"]):
                logger.info(
                    "Dropping late-identified bumper for %s confirmation %d: cooldown "
                    "window (ping at %d) already superseded by bump at %d",
                    entry["service"],
                    row["message_id"],
                    int(entry["ping_at"]),
                    last,
                )
                continue

            await add_to_waitlist(entry["guild_id"], bumper.id, entry["service"], entry["ping_at"])
            logger.info(
                "Late-identified bumper %s (%d) for %s confirmation %d in guild %d; "
                "ping due at %d",
                bumper,
                bumper.id,
                entry["service"],
                row["message_id"],
                entry["guild_id"],
                entry["ping_at"],
            )

    async def _fetch_message_anywhere(
        self,
        message_id: int,
        channel_id: Optional[int],
        guild_id: Optional[int] = None,
    ) -> Optional[discord.Message]:
        """Fetch a message by id: from the recorded channel first, then from
        the rest of the guild's channels (covers a changed/deleted channel
        record). Returns None if no fetch succeeds."""
        channels = []
        if channel_id is not None:
            channel = self.bot.get_channel(channel_id)
            if channel is not None and hasattr(channel, "fetch_message"):
                channels.append(channel)

        if guild_id is not None:
            guild = self.bot.get_guild(guild_id)
            if guild is not None:
                for channel in guild.channels:
                    if hasattr(channel, "fetch_message") and all(c.id != channel.id for c in channels):
                        channels.append(channel)

        for channel in channels:
            try:
                return await channel.fetch_message(message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue
        return None

    async def _repair_backfill_message(self, msg: discord.Message) -> bool:
        """Repair one backfilled confirmation whose bumper missed the waitlist.

        on_message can process a confirmation without adding its bumper: the
        duplicate/at-or-before guards skip restart duplicates, and the cached
        identity may be missing (queued for retry instead). A fresh fetch
        usually carries the interaction metadata, so the row can be backfilled.

        Returns True if a bumper was added. Only still-active cooldown windows
        are repaired: an expired ping_at was either delivered already or would
        be pointless noise. The add is an upsert, so a retry-loop resolution of
        the same confirmation can never produce a second row or a double ping.
        """
        if not msg.guild:
            return False

        # Only successful bumps may be repaired. Cooldown/failure notices are
        # bump-bot messages too, and crediting them would put people on the
        # waitlist for bumps that never happened (seen live: an "You're on
        # cooldown" notice added a phantom entry after a restart).
        service = await detect_bump(msg)
        if service is None:
            await self.on_message(msg)  # keep logging/state handling consistent
            return False

        cooldown = CARL_COOLDOWN if service == "carl" else DISBOARD_COOLDOWN
        ping_at = int((msg.created_at + cooldown).timestamp())
        now = int(datetime.now(timezone.utc).timestamp())
        if ping_at <= now:
            # Expired window: let on_message record the state/mark-seen part;
            # it will not add an expired window to the waitlist.
            await self.on_message(msg)
            return False

        bumper = self._find_bumper(msg)
        if bumper is None and msg.reference and msg.reference.message_id:
            bumper = await self._resolve_bumper_from_reference(msg)
        if bumper is None:
            # Still unidentifiable: on_message (called below) queues it for the
            # identity-retry loop if it wasn't already.
            await self.on_message(msg)
            return False

        # Is this confirmation's window already covered on the waitlist?
        rows = await get_guild_waitlist(msg.guild.id)
        if any(r["service"] == service and int(r["ping_at"]) == ping_at for r in rows):
            await self.on_message(msg)  # keep dedupe/state handling intact
            return False

        await self.on_message(msg)  # record state / mark seen if applicable
        await add_to_waitlist(msg.guild.id, bumper.id, service, ping_at)
        # If a previous pass queued this confirmation for identity retry,
        # it is resolved now - drop the queue entry (no-op if absent).
        await drop_pending_bumper(msg.id)
        logger.info(
            "Bump backfill repair: added %s (%d) to the waitlist from "
            "confirmation %d in guild %d",
            bumper,
            bumper.id,
            msg.id,
            msg.guild.id,
        )
        return True

    async def _backfill_recent_bumps(self) -> None:
        """Re-scan recent bump-bot messages after startup and reprocess them.

        Covers the restart blind spot: bump confirmations posted while the bot
        was down never generate MESSAGE_CREATE events. on_message is safe to
        call again on the same messages - the duplicate-message-id check and
        the Disboard cooldown guard prevent double-counting.
        """
        try:
            await self.bot.wait_until_ready()
            for guild in list(self.bot.guilds):
                try:
                    if not await is_guild_enabled(guild.id):
                        continue
                    settings = await get_guild_settings(guild.id)
                    channel_id = settings.get("notification_channel_id")
                    channel = guild.get_channel(channel_id) if channel_id else None
                    if channel is None or not hasattr(channel, "history"):
                        continue

                    processed = 0
                    repaired = 0
                    seen = self._seen_confirmation_ids.setdefault(guild.id, set())
                    async for msg in channel.history(limit=100):
                        if msg.author.id in (CARL_BOT_ID, DISBOARD_BOT_ID) or msg.application_id in (
                            CARL_BOT_ID,
                            DISBOARD_BOT_ID,
                        ):
                            seen.add(msg.id)  # the periodic scan skips these
                            if await self._repair_backfill_message(msg):
                                repaired += 1
                            processed += 1
                    if processed:
                        logger.info(
                            "Bump backfill: reprocessed %d bump-bot message(s) in guild %d (#%s), %d repaired",
                            processed,
                            guild.id,
                            channel.id,
                            repaired,
                        )
                except Exception:
                    logger.exception("Bump backfill failed for guild %s", guild.id)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Bump backfill crashed")

    async def _resolve_bumper_from_reference(self, message: discord.Message) -> Optional[Union[discord.Member, discord.User]]:
        """Fetch the referenced message fresh and read the invoking user out of it."""
        reference = message.reference
        channel = getattr(message, "channel", None)
        if channel is None or not hasattr(channel, "fetch_message"):
            return None

        try:
            ref_msg = await channel.fetch_message(reference.message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

        if not isinstance(ref_msg, discord.Message):
            return None

        # Marker authored by a real user -> that's the bumper.
        if not ref_msg.author.bot:
            return ref_msg.author

        # Otherwise read interaction_metadata.user (carried by Carl-bot's reply).
        meta = getattr(ref_msg, "interaction_metadata", None)
        if meta is not None:
            user = getattr(meta, "user", None)
            if user is not None:
                return user

        interaction = getattr(ref_msg, "interaction", None)
        if interaction is not None:
            user = getattr(interaction, "user", None)
            if user is not None:
                return user

        return None


    # ==================== USER COMMANDS ====================

    @bump_notification_group.command(name="status", description="Check your personal bump waitlist status")
    async def bump_notification_status(self, interaction: discord.Interaction) -> None:
        """Show the user's entries on the bump waitlist."""
        entries = await get_guild_waitlist(interaction.guild_id)
        mine = [e for e in entries if e["user_id"] == interaction.user.id]

        embed = discord.Embed(
            title="🔔 Your Bump Waitlist Status",
            color=discord.Color.blue() if mine else discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )

        if mine:
            lines = []
            for e in mine:
                display = "Carl-bot" if e["service"] == "carl" else "Disboard"
                lines.append("**{}**: ping <t:{}:R>".format(display, int(e["ping_at"])))
            embed.add_field(
                name="Waiting ({} entries)".format(len(mine)),
                value="\n".join(lines),
                inline=False,
            )
            embed.description = (
                "Bump with Carl-bot or Disboard and you'll be pinged here "
                "when your personal cooldown (6h Carl / 2h Disboard) is up."
            )
        else:
            embed.description = (
                "You're not on the waitlist. **Bump the server** with `/bump` "
                "(Carl-bot) or Disboard's bump to get on it - you'll be pinged "
                "when your cooldown (6h Carl / 2h Disboard) expires."
            )

        embed.set_footer(text="User: {}".format(interaction.user), icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ==================== ADMIN CONFIG COMMANDS ====================

    @bump_config_group.command(name="enabled", description="Enable or disable the bump system")
    @app_commands.describe(state="Enable or disable the bump system")
    @app_commands.choices(state=[
        app_commands.Choice(name="Enable", value="on"),
        app_commands.Choice(name="Disable", value="off"),
    ])
    async def bump_config_enabled(self, interaction: discord.Interaction, state: app_commands.Choice[str]) -> None:
        """Enable or disable the bump system for this server."""
        enabled = state.value == "on"
        await update_guild_settings(interaction.guild_id, enabled=enabled)

        await interaction.response.send_message(
            "✅ Bump system **{}** for this server.".format("enabled" if enabled else "disabled"),
            ephemeral=True,
        )

    @bump_config_group.command(name="channel", description="Set the notification channel")
    @app_commands.describe(channel="Channel to send bump reminders")
    async def bump_config_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        """Set the notification channel for bump reminders."""
        # Verify bot has permissions
        perms = channel.permissions_for(interaction.guild.me)
        if not perms.send_messages or not perms.embed_links:
            await interaction.response.send_message(
                "❌ I don't have permission to send messages and embeds in {}!".format(channel.mention),
                ephemeral=True,
            )
            return

        await update_guild_settings(interaction.guild_id, notification_channel_id=channel.id)

        await interaction.response.send_message(
            "✅ Bump notification channel set to {}".format(channel.mention),
            ephemeral=True,
        )

    @bump_config_group.command(name="view", description="View current bump configuration and waitlist")
    async def bump_config_view(self, interaction: discord.Interaction) -> None:
        """View current bump configuration plus everyone on the personal waitlist."""
        settings = await get_guild_settings(interaction.guild_id)
        channel_id = settings.get("notification_channel_id")
        channel = interaction.guild.get_channel(channel_id) if channel_id else None

        waitlist = await get_guild_waitlist(interaction.guild_id)

        embed = discord.Embed(
            title="🔔 Bump System Configuration",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="🔧 Status",
            value="🟢 Enabled" if settings.get("enabled", True) else "🔴 Disabled",
            inline=True,
        )

        embed.add_field(
            name="📍 Notification Channel",
            value=channel.mention if channel else "`Not set`",
            inline=True,
        )

        embed.add_field(
            name="👥 On Waitlist",
            value=str(len(waitlist)),
            inline=True,
        )

        embed.description = (
            "Everyone who bumps is on the waitlist with a personal cooldown "
            "(6h Carl-bot / 2h Disboard). They get pinged personally in the "
            "notification channel when it expires, then removed from here."
        )

        if waitlist:
            now = int(datetime.now(timezone.utc).timestamp())
            lines = []
            for e in waitlist:
                display = "Carl-bot" if e["service"] == "carl" else "Disboard"
                member = interaction.guild.get_member(e["user_id"])
                if member:
                    name = "{}: {}".format(member.mention, member.display_name)
                else:
                    name = "<@{}> (left guild)".format(e["user_id"])

                remaining = e["ping_at"] - now
                if remaining <= 0:
                    due_str = "**due now**"
                else:
                    due_str = "<t:{}:R>".format(int(e["ping_at"]))

                lines.append("{} - {} - {}".format(name, display, due_str))

            embed.add_field(
                name="⏳ Waitlist ({} entries)".format(len(lines)),
                value="\r\n".join(lines)[:1024],
                inline=False,
            )
        else:
            embed.add_field(
                name="⏳ Waitlist",
                value="Empty - bump to get on it",
                inline=False,
            )

        embed.set_footer(text="Guild: {}".format(interaction.guild.name), icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ==================== ADMIN TEST COMMANDS ====================

    @bump_test_group.command(name="cycle", description="Full fast cycle: put YOU on the waitlist, ping in ~1 minute")
    @app_commands.describe(service="Which service to simulate")
    @app_commands.choices(service=[
        app_commands.Choice(name="Carl-bot", value="carl"),
        app_commands.Choice(name="Disboard", value="disboard"),
    ])
    async def bump_test_cycle(self, interaction: discord.Interaction, service: app_commands.Choice[str]) -> None:
        """Simulate the invoking user bumping, with a ~60 second waitlist timer
        so the full pipeline (waitlist -> due -> claim -> personal ping ->
        removal) can be tested without waiting the real 2h/6h."""
        due = int((datetime.now(timezone.utc) + timedelta(seconds=60)).timestamp())
        await add_to_waitlist(interaction.guild_id, interaction.user.id, service.value, due)

        await interaction.response.send_message(
            "🧪 Put **you** on the waitlist for a simulated **{}** bump.\n"
            "The scheduler (checks every 30s) will ping you personally in the "
            "notification channel in ~1 minute, then remove you from the list.\n"
            "Ping due at: <t:{}:T>".format(service.value.capitalize(), due),
            ephemeral=True,
        )

    @bump_test_group.command(name="ping", description="Send a sample personal bump ping now")
    async def bump_test_ping(self, interaction: discord.Interaction) -> None:
        """Send a sample personal ping so the user can verify the reminder
        format without changing the waitlist."""
        from bot.services.bump_notifier import send_test_ping
        success = await send_test_ping(self.bot, interaction.guild_id, interaction.user.id, "carl")
        if success:
            await interaction.response.send_message(
                "✅ Sample ping sent to the notification channel - check it!",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "❌ Failed to send sample ping. Check the notification channel and my permissions.",
                ephemeral=True,
            )

    @bump_test_group.command(name="debugme", description="Show raw fields of a bump-bot message (diagnostics)")
    @app_commands.describe(message_id="Message ID to inspect (optional, analyzes last Carl/Disboard message)")
    async def bump_test_debugme(self, interaction: discord.Interaction, message_id: Optional[str] = None) -> None:
        """Dump the raw fields that decide bump detection for a real message.

        Temporary diagnostics for the Carl-bot detection bug: shows author ID,
        application ID, webhook ID, message type, content, embeds, and the
        invoking interaction user so we can see exactly what Discord sends.
        """
        if message_id:
            try:
                msg_id = int(message_id)
                message = await interaction.channel.fetch_message(msg_id)
            except (ValueError, discord.NotFound):
                await interaction.response.send_message("❌ Invalid message ID or message not found.", ephemeral=True)
                return
        else:
            from bot.config.bump_config import CARL_BOT_ID as _CARL
            from bot.config.bump_config import DISBOARD_BOT_ID as _DIS
            async for msg in interaction.channel.history(limit=20):
                if msg.author.id in (_CARL, _DIS):
                    message = msg
                    break
            else:
                await interaction.response.send_message("❌ No recent Carl-bot or Disboard message found.", ephemeral=True)
                return

        info = debug_bump_detection(message)

        embed = discord.Embed(
            title="🔬 Bump Message Diagnostics",
            color=discord.Color.dark_teal(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="Author",
            value="{}\nID: `{}` (bot={})".format(info["author_name"], info["author_id"], info["author_bot"]),
            inline=True,
        )
        embed.add_field(
            name="Application ID",
            value="`{}`".format(info["application_id"]) if info["application_id"] else "`None`",
            inline=True,
        )
        embed.add_field(
            name="Webhook ID",
            value="`{}`".format(info["webhook_id"]) if info["webhook_id"] else "`None`",
            inline=True,
        )
        embed.add_field(name="Message Type", value=str(info["message_type"]), inline=True)
        embed.add_field(
            name="Channel / Guild",
            value="<#{0}>\n`{0}` / `{1}`".format(info["channel_id"], info["guild_id"]),
            inline=True,
        )
        embed.add_field(
            name="Interaction User",
            value=("{} (`{}`)".format(info["interaction_user"], info["interaction_user_id"])
                   if info.get("interaction_user") else "`None`"),
            inline=True,
        )
        embed.add_field(
            name="Content",
            value=(info["content"][:500] or "*empty*"),
            inline=False,
        )

        embed.add_field(
            name="Identity Match",
            value="Carl: {} | Disboard: {}".format(
                "✅" if info["is_carl"] else "❌",
                "✅" if info["is_disboard"] else "❌",
            ),
            inline=True,
        )
        embed.add_field(
            name="Detection Result",
            value="Carl: {} | Disboard: {}".format(
                "✅" if info["carl_success"] else "❌",
                "✅" if info["disboard_success"] else "❌",
            ),
            inline=True,
        )
        embed.add_field(
            name="Keywords Seen",
            value=(
                "Carl +: {} | Carl -: {}\nDisboard +: {} | Disboard -: {}".format(
                    ", ".join(info["carl_success_keywords"]) or "-",
                    ", ".join(info["carl_failure_keywords"]) or "-",
                    ", ".join(info["disboard_success_keywords"]) or "-",
                    ", ".join(info["disboard_failure_keywords"]) or "-",
                )
            ),
            inline=False,
        )

        if info.get("embeds"):
            for e in info["embeds"][:3]:
                val = ""
                if e["title"]:
                    val += "Title: {}\n".format(e["title"][:100])
                if e["description"]:
                    val += "Desc: {}\n".format(e["description"][:150])
                for f in e["fields"][:3]:
                    val += "Field '{}': {}\n".format(f["name"][:50], f["value"][:100])
                embed.add_field(name="Embed #{}".format(e["index"]), value=val[:1024] or "*empty*", inline=False)

        if info.get("reference_message_id"):
            embed.add_field(
                name="Reply Reference",
                value="Message `{}`".format(info["reference_message_id"]),
                inline=False,
            )

        embed.set_footer(text="Success requires: bot identity + success phrase in content/embeds")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bump_test_group.command(name="detection", description="Debug bump detection for a message")
    @app_commands.describe(message_id="Message ID to analyze (optional, analyzes last bot message)")
    async def bump_test_detection(self, interaction: discord.Interaction, message_id: Optional[str] = None) -> None:
        """Debug bump detection for a specific message."""
        if message_id:
            try:
                msg_id = int(message_id)
                message = await interaction.channel.fetch_message(msg_id)
            except (ValueError, discord.NotFound):
                await interaction.response.send_message("❌ Invalid message ID or message not found.", ephemeral=True)
                return
        else:
            # Find last bot message in channel
            async for msg in interaction.channel.history(limit=20):
                if msg.author.id in (302050872383242240, 235148962103951360):
                    message = msg
                    break
            else:
                await interaction.response.send_message("❌ No recent Carl-bot or Disboard message found.", ephemeral=True)
                return

        debug_info = debug_bump_detection(message)

        embed = discord.Embed(
            title="🔍 Bump Detection Debug",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(name="Author", value="{} ({})".format(debug_info['author_name'], debug_info['author_id']), inline=True)
        embed.add_field(name="Is Carl-bot", value="✅ Yes" if debug_info['is_carl'] else "❌ No", inline=True)
        embed.add_field(name="Is Disboard", value="✅ Yes" if debug_info['is_disboard'] else "❌ No", inline=True)
        embed.add_field(name="Carl Success", value="✅ Yes" if debug_info['carl_success'] else "❌ No", inline=True)
        embed.add_field(name="Disboard Success", value="✅ Yes" if debug_info['disboard_success'] else "❌ No", inline=True)
        embed.add_field(name="Content Preview", value=debug_info['content'][:200] or "*empty*", inline=False)

        if debug_info['carl_failure_keywords']:
            embed.add_field(name="❌ Carl Failure Keywords", value=", ".join(debug_info['carl_failure_keywords']), inline=True)
        if debug_info['disboard_failure_keywords']:
            embed.add_field(name="❌ Disboard Failure Keywords", value=", ".join(debug_info['disboard_failure_keywords']), inline=True)
        if debug_info['carl_success_keywords']:
            embed.add_field(name="✅ Carl Success Keywords", value=", ".join(debug_info['carl_success_keywords']), inline=True)
        if debug_info['disboard_success_keywords']:
            embed.add_field(name="✅ Disboard Success Keywords", value=", ".join(debug_info['disboard_success_keywords']), inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bump_test_group.command(name="status", description="Show detailed bump system status")
    async def bump_test_status(self, interaction: discord.Interaction) -> None:
        """Show detailed bump system status for administrators."""
        settings = await get_guild_settings(interaction.guild_id)
        states = await get_all_guild_bump_states(interaction.guild_id)

        embed = discord.Embed(
            title="🔔 Bump System Status",
            color=discord.Color.blue() if settings.get("enabled", True) else discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="🔧 System",
            value="🟢 Enabled" if settings.get("enabled", True) else "🔴 Disabled",
            inline=True,
        )

        channel_id = settings.get("notification_channel_id")
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        embed.add_field(
            name="📍 Channel",
            value=channel.mention if channel else "`Not set`",
            inline=True,
        )

        # Per-person waitlist
        waitlist = await get_guild_waitlist(interaction.guild_id)
        if waitlist:
            lines = []
            for e in waitlist[:15]:
                display = "Carl-bot" if e["service"] == "carl" else "Disboard"
                member = interaction.guild.get_member(e["user_id"])
                name = member.mention if member else "<@{}>".format(e["user_id"])
                lines.append("{} - {}: ping <t:{}:R>".format(name, display, int(e["ping_at"])))
            if len(waitlist) > 15:
                lines.append("*...and {} more*".format(len(waitlist) - 15))
            embed.add_field(
                name="⏳ Waitlist ({} waiting)".format(len(waitlist)),
                value="\n".join(lines)[:1024],
                inline=False,
            )
        else:
            embed.add_field(
                name="⏳ Waitlist",
                value="Empty - bump to get on it",
                inline=False,
            )

        # Server-level last-bump state (informational; Disboard cooldown guard)
        state_lines = []
        for service in ["carl", "disboard"]:
            state = states.get(service)
            display_name = "Carl-bot" if service == "carl" else "Disboard"
            if state and state.get("last_successful_bump"):
                state_lines.append("{}: last bump <t:{}:R>".format(display_name, int(state["last_successful_bump"])))
            else:
                state_lines.append("{}: no bump recorded".format(display_name))
        embed.add_field(
            name="📊 Last Bumps",
            value="\n".join(state_lines),
            inline=False,
        )

        embed.set_footer(text="Guild: {}".format(interaction.guild.name))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bump_test_group.command(name="reset", description="Reset bump cooldown for testing")
    @app_commands.describe(service="Which service to reset")
    @app_commands.choices(service=[
        app_commands.Choice(name="Carl-bot", value="carl"),
        app_commands.Choice(name="Disboard", value="disboard"),
    ])
    async def bump_test_reset(self, interaction: discord.Interaction, service: app_commands.Choice[str]) -> None:
        """Reset bump state for a service."""
        await reset_bump_state(interaction.guild_id, service.value)
        await interaction.response.send_message(
            "⚠️ Reset **{}** bump state for this server.\n"
            "Cooldown cleared, next bump available immediately.".format(service.value.capitalize()),
            ephemeral=True,
        )

    @bump_test_group.command(name="clearwaitlist", description="Remove everyone from the bump waitlist")
    async def bump_test_clearwaitlist(self, interaction: discord.Interaction) -> None:
        """Clear the whole waitlist (e.g. after a notification-channel mixup)."""
        removed = await clear_guild_waitlist(interaction.guild_id)
        await interaction.response.send_message(
            "🗑️ Removed **{}** entr{} from the waitlist.".format(removed, "y" if removed == 1 else "ies"),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    """Set up the bump cog."""
    await bot.add_cog(BumpCog(bot))
