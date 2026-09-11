"""End-to-end tests for the bump detection + waitlist pipeline.

Run from project root:  python tests/test_bump_pipeline.py

Covers:
  1. Carl-bot detection (exact screenshot text, classic wording, embed variants,
     failure messages, wrong-author rejection, APP-message application_id path)
  2. DISBOARD detection (existing behavior preserved)
  3. Both platforms for the same user -> separate waitlist rows
  4. Cooldown expiry + per-person ping, then removal (no duplicates)
  5. Notification-disabled guild -> entries are left in place
  6. Restart persistence: entries survive a "restart" (new process, same DB)
"""

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Point the DB layer at a throwaway database BEFORE importing bump_db.
_tmp_dir = tempfile.mkdtemp(prefix="bump_test_")
os.environ.setdefault("DISCORD_TOKEN", "test-token-not-real")

import config  # noqa: E402
config.Config.DATA_DIR = Path(_tmp_dir)  # type: ignore[assignment]

import discord  # noqa: E402

from bot.config.bump_config import (  # noqa: E402
    CARL_BOT_ID,
    DISBOARD_BOT_ID,
)
from bot.database import bump_db  # noqa: E402
from bot.services.bump_detector import (  # noqa: E402
    debug_bump_detection,
    detect_bump,
    is_carl_bump_success,
    is_disboard_bump_success,
)
from bot.services.bump_notifier import BumpScheduler  # noqa: E402
from bot.cogs.bump import BumpCog  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def make_message(
    *,
    author_id: int,
    content: str = "",
    embeds=None,
    application_id=None,
    webhook_id=None,
    interaction_user_id=None,
    reference_message_id=None,
    bot_author=True,
    guild_id: int = 987654321098765432,
):
    """Build a stand-in for discord.Message with the fields detection uses."""
    author = SimpleNamespace(id=author_id, bot=bot_author, name="Bumper", __str__=lambda s: "Bumper")
    msg = SimpleNamespace()
    msg.author = author
    msg.content = content
    msg.embeds = list(embeds or [])
    msg.application_id = application_id
    msg.webhook_id = webhook_id
    msg.channel = SimpleNamespace(id=123456789012345678)
    msg.guild = SimpleNamespace(id=guild_id, get_member=lambda uid: None)
    msg.type = discord.MessageType.default
    msg.id = 555000000000000001
    if interaction_user_id is not None:
        msg.interaction_metadata = SimpleNamespace(user=SimpleNamespace(id=interaction_user_id))
    else:
        msg.interaction_metadata = None
    msg.interaction = None
    msg.created_at = datetime.now(timezone.utc)
    msg.reference = (
        SimpleNamespace(message_id=reference_message_id, resolved=None) if reference_message_id else None
    )
    return msg


def make_embed(title=None, description=None, fields=None):
    emb = MagicMock()
    emb.title = title
    emb.description = description
    emb.fields = fields or []
    return emb


def make_field(name, value):
    f = MagicMock()
    f.name = name
    f.value = value
    return f


# ============================== 1. CARL-BOT ==============================

print("\n[1] Carl-bot detection")


async def test_carl():
    # Exact text from the user's screenshot
    msg = make_message(author_id=CARL_BOT_ID, content="You've successfully bumped this server, it is now ranked 528 out of 24120 servers!")
    check("screenshot text (content)", is_carl_bump_success(msg) is True)
    check("detect_bump returns carl", await detect_bump(msg) == "carl")

    # The same message but as an APP message attributed to the invoking user's
    # member object - the reliable signal is application_id.
    msg = make_message(author_id=999999999999999999, application_id=CARL_BOT_ID, content="You've successfully bumped this server, it is now ranked 528 out of 24120 servers!")
    check("APP message via application_id", is_carl_bump_success(msg) is True)

    # Classic Carl wording: success + wait phrase in the same sentence.
    msg = make_message(author_id=CARL_BOT_ID, content="You've successfully bumped this server, it is now ranked 528 out of 24120 servers! You have to wait 6 hours before you can bump again.")
    check("classic wording incl. 'wait' phrase", is_carl_bump_success(msg) is True)

    # Discord bold formatting inside the content.
    msg = make_message(author_id=CARL_BOT_ID, content="**You've successfully bumped this server**, it is now ranked 528!")
    check("bold markdown around success", is_carl_bump_success(msg) is True)

    # Success inside an embed description.
    msg = make_message(author_id=CARL_BOT_ID, embeds=[make_embed(description="You've successfully bumped this server, it is now ranked 528 out of 24120 servers!")])
    check("success in embed description", is_carl_bump_success(msg) is True)

    # Success inside an embed field.
    msg = make_message(author_id=CARL_BOT_ID, embeds=[make_embed(fields=[make_field("Bump", "successfully bumped this server")])])
    check("success in embed field", is_carl_bump_success(msg) is True)

    # Standalone failure messages must NOT count.
    for text in (
        "You have to wait 3 hours before you can bump this server again!",
        "This server can be bumped again <t:1700000000:R>",
        "You've already bumped this server",
        "The bump command has a cooldown",
    ):
        msg = make_message(author_id=CARL_BOT_ID, content=text)
        check(f"failure rejected: {text[:40]!r}", is_carl_bump_success(msg) is False)

    # Wrong author (member hydration) and random bots must NOT count.
    msg = make_message(author_id=999999999999999999, content="You've successfully bumped this server!")
    check("wrong author rejected", is_carl_bump_success(msg) is False)
    msg = make_message(author_id=DISBOARD_BOT_ID, content="You've successfully bumped this server!")
    check("disboard author not counted for carl", is_carl_bump_success(msg) is False)


# ============================== 2. DISBOARD ==============================

print("\n[2] DISBOARD detection (existing behavior)")


async def test_disboard():
    msg = make_message(author_id=DISBOARD_BOT_ID, content="**Bump done!** :thumbsup:")
    check("disboard 'Bump done!'", is_disboard_bump_success(msg) is True)
    check("detect_bump returns disboard", await detect_bump(msg) == "disboard")

    msg = make_message(author_id=DISBOARD_BOT_ID, content="Bump again in 2 hours!")
    check("disboard 'bump again in'", is_disboard_bump_success(msg) is True)

    # Disboard pings the bumper at the start: the mention is how the bumper is
    # identified. Detection must still succeed.
    msg = make_message(author_id=DISBOARD_BOT_ID, content="<@123456789012345678> **Bump done!**")
    check("disboard with user mention", is_disboard_bump_success(msg) is True)

    # Failure wording rejected.
    msg = make_message(author_id=DISBOARD_BOT_ID, content="Please wait 2 more hours to bump this server")
    check("disboard failure rejected", is_disboard_bump_success(msg) is False)

    # Generic keywords are shared between platforms on purpose; the platform
    # discriminator is the author/application id, exactly as in the old code.
    msg = make_message(author_id=DISBOARD_BOT_ID, content="You've successfully bumped this server, it is now ranked 528 out of 24120 servers!")
    check("generic keyword + disboard author = disboard (old parity)", is_disboard_bump_success(msg) is True)


# ====================== 3. DATABASE + WAITLIST FLOW ======================

print("\n[3] Database: platform-specific waitlist + cooldown expiry")


async def test_db_flow():
    await bump_db.init_db()
    guild = 111111111111111111
    user = 123456789012345678
    channel_id = 123456789012345678

    # Both platforms for the same user -> two separate rows.
    now = datetime.now(timezone.utc)
    await bump_db.add_to_waitlist(guild, user, "carl", int((now + timedelta(hours=6)).timestamp()))
    await bump_db.add_to_waitlist(guild, user, "disboard", int((now + timedelta(hours=2)).timestamp()))

    rows = await bump_db.get_guild_waitlist(guild)
    check("two rows for one user (carl + disboard)", len(rows) == 2, f"got {len(rows)}")
    services = {r["service"] for r in rows}
    check("services are carl and disboard", services == {"carl", "disboard"}, str(services))
    carl_row = next(r for r in rows if r["service"] == "carl")
    dis_row = next(r for r in rows if r["service"] == "disboard")
    check("carl cooldown is 6h", abs(carl_row["ping_at"] - int((now + timedelta(hours=6)).timestamp())) < 5)
    check("disboard cooldown is 2h", abs(dis_row["ping_at"] - int((now + timedelta(hours=2)).timestamp())) < 5)

    # Re-bump after cooldown expires -> same row refreshed, no duplicates.
    await bump_db.add_to_waitlist(guild, user, "carl", int((now + timedelta(hours=12)).timestamp()))
    rows = await bump_db.get_guild_waitlist(guild)
    check("re-bump refreshes row (no duplicate)", len(rows) == 2, f"got {len(rows)}")
    carl_row = next(r for r in rows if r["service"] == "carl")
    check("re-bump extends carl ping_at", abs(carl_row["ping_at"] - int((now + timedelta(hours=12)).timestamp())) < 5)

    # A late-attributed OLDER confirmation must never shorten a cooldown.
    await bump_db.add_to_waitlist(guild, user, "carl", int((now + timedelta(hours=1)).timestamp()))
    rows = await bump_db.get_guild_waitlist(guild)
    carl_row = next(r for r in rows if r["service"] == "carl")
    check("older confirmation can't shorten cooldown", abs(carl_row["ping_at"] - int((now + timedelta(hours=12)).timestamp())) < 5)

    # Simulate restart: the DB file is on disk; entries must still be there.
    rows = await bump_db.get_guild_waitlist(guild)
    check("entries persist (restart survival)", len(rows) == 2)

    # Nothing is due yet.
    due = await bump_db.get_due_waitlist()
    check("nothing due yet", len(due) == 0, f"got {len(due)}")

    # Make entries due by rewinding the recorded ping times directly
    # (add_to_waitlist only ever extends a cooldown, by design).
    db = await bump_db.get_db()
    await db.execute(
        "UPDATE bump_waitlist SET ping_at = ? WHERE guild_id = ?",
        (int((now - timedelta(seconds=1)).timestamp()), guild),
    )
    await db.commit()
    await db.close()

    # The scheduler only delivers to the CONFIGURED notification channel.
    await bump_db.update_guild_settings(guild, notification_channel_id=channel_id)

    sent = []

    async def fake_send(*args, **kwargs):
        sent.append(kwargs.get("content", args[0] if args else ""))
        return None

    channel = MagicMock()
    channel.id = channel_id
    channel.send = fake_send
    channel.guild = SimpleNamespace(me=SimpleNamespace(id=111))
    channel.permissions_for = lambda _me: SimpleNamespace(send_messages=True)
    channel.mention = f"<#{channel_id}>"

    bot = MagicMock()
    bot.get_channel = lambda _cid: channel if _cid == channel_id else None

    scheduler = BumpScheduler(bot)
    await scheduler._check_and_ping()

    check("both due users pinged", len(sent) == 2, f"sent={sent}")
    check("ping mentions the user", all("<@123456789012345678>" in s for s in sent))
    check("carl ping says Carl-bot", any("Carl-bot" in s for s in sent), str(sent))
    check("disboard ping says Disboard", any("Disboard" in s for s in sent), str(sent))

    rows = await bump_db.get_guild_waitlist(guild)
    check("waitlist empty after pings", len(rows) == 0, f"got {len(rows)}")

    # Second pass must not re-ping (no duplicates).
    await scheduler._check_and_ping()
    check("no duplicate notifications on re-run", len(sent) == 2, f"sent={len(sent)}")


async def test_notifications_disabled():
    print("\n[4] Notification toggle")
    await bump_db.init_db()
    guild = 222222222222222222
    user = 123456789012345678
    channel_id = 123456789012345678

    # Disable notifications for the guild.
    await bump_db.update_guild_settings(guild, enabled=False)
    check("guild disabled flag stored", (await bump_db.is_guild_enabled(guild)) is False)

    now = datetime.now(timezone.utc)
    await bump_db.add_to_waitlist(guild, user, "carl", int((now - timedelta(seconds=1)).timestamp()))

    sent = []

    async def fake_send(*args, **kwargs):
        sent.append(kwargs.get("content", args[0] if args else ""))

    channel = MagicMock()
    channel.send = fake_send
    channel.id = channel_id
    channel.guild = SimpleNamespace(me=SimpleNamespace(id=111))
    channel.permissions_for = lambda _me: SimpleNamespace(send_messages=True)
    channel.mention = f"<#{channel_id}>"

    bot = MagicMock()
    bot.get_channel = lambda _cid: channel if _cid == channel_id else None

    scheduler = BumpScheduler(bot)
    await scheduler._check_and_ping()
    check("no ping when notifications disabled", len(sent) == 0, f"sent={sent}")

    # Entry must still be on the waitlist (nothing lost, retried later).
    rows = await bump_db.get_guild_waitlist(guild)
    check("entry retained while disabled", len(rows) == 1, f"got {len(rows)}")

    # Re-enable: the due entry is delivered on the next pass.
    await bump_db.update_guild_settings(guild, enabled=True, notification_channel_id=channel_id)
    await scheduler._check_and_ping()
    check("ping delivered after re-enable", len(sent) == 1, f"sent={sent}")
    rows = await bump_db.get_guild_waitlist(guild)
    check("entry removed after delivery", len(rows) == 0, f"got {len(rows)}")


async def test_on_message_pipeline():
    """Run real Carl/Disboard messages through BumpCog.on_message."""
    print("\n[6] on_message pipeline (Carl + Disboard + both platforms)")
    await bump_db.init_db()
    guild = 333333333333333333
    user = 123456789012345678

    cog = BumpCog(MagicMock())
    cog.bot.get_user = lambda uid: SimpleNamespace(id=uid)

    async def ok(guild_id):
        return True

    async def record(guild_id, service, bump_time, message_id=None):
        return await bump_db.record_successful_bump(guild_id, service, bump_time, message_id)

    async def seen(guild_id, service, message_id):
        return await bump_db.mark_bump_message_seen(guild_id, service, message_id)

    async def dup(guild_id, service, message_id):
        return await bump_db.check_duplicate_bump(guild_id, service, message_id)

    async def state(guild_id, service):
        return await bump_db.get_bump_state(guild_id, service)

    # Patch the db functions the cog references (imported into its namespace).
    with patch("bot.cogs.bump.is_guild_enabled", ok), \
         patch("bot.cogs.bump.record_successful_bump", record), \
         patch("bot.cogs.bump.mark_bump_message_seen", seen), \
         patch("bot.cogs.bump.check_duplicate_bump", dup), \
         patch("bot.cogs.bump.get_bump_state", state):
        now = datetime.now(timezone.utc)

        # -- Carl-bot success (exact screenshot text, APP message) --
        carl_msg = make_message(
            author_id=CARL_BOT_ID,
            content="You've successfully bumped this server, it is now ranked 528 out of 24120 servers!",
            application_id=CARL_BOT_ID,
            interaction_user_id=user,
            guild_id=guild,
        )
        carl_msg.id = 777000000000000001
        await cog.on_message(carl_msg)
        rows = [r for r in await bump_db.get_guild_waitlist(guild) if r["service"] == "carl"]
        check("carl: user added to waitlist", len(rows) == 1, str(rows))
        if rows:
            check(
                "carl: 6h cooldown",
                abs(rows[0]["ping_at"] - int((now + timedelta(hours=6)).timestamp())) < 30,
                str(rows[0]["ping_at"]),
            )
        st = await bump_db.get_bump_state(guild, "carl")
        check("carl: bump_state row written", st is not None)

        # -- DISBOARD success (mention + Bump done) --
        dis_msg = make_message(
            author_id=DISBOARD_BOT_ID,
            content=f"<@{user}> **Bump done!** :thumbsup:",
            guild_id=guild,
        )
        dis_msg.id = 777000000000000002
        await cog.on_message(dis_msg)
        rows = [r for r in await bump_db.get_guild_waitlist(guild) if r["service"] == "disboard"]
        check("disboard: user added to waitlist", len(rows) == 1, str(rows))
        if rows:
            check(
                "disboard: 2h cooldown",
                abs(rows[0]["ping_at"] - int((now + timedelta(hours=2)).timestamp())) < 30,
                str(rows[0]["ping_at"]),
            )

        total = await bump_db.get_guild_waitlist(guild)
        check("both platforms for same user: 2 rows", len(total) == 2, f"got {len(total)}")

        # -- Duplicate Carl message id must not double-count --
        carl_msg2 = make_message(
            author_id=CARL_BOT_ID,
            content="You've successfully bumped this server, it is now ranked 528 out of 24120 servers!",
            application_id=CARL_BOT_ID,
            interaction_user_id=user,
            guild_id=guild,
        )
        carl_msg2.id = 777000000000000001
        await cog.on_message(carl_msg2)
        total = await bump_db.get_guild_waitlist(guild)
        check("duplicate message id ignored", len(total) == 2, f"got {len(total)}")

        # -- Second DISBOARD confirmation inside cooldown is ignored --
        dis_msg2 = make_message(author_id=DISBOARD_BOT_ID, content=f"<@{user}> **Bump done!**", guild_id=guild)
        dis_msg2.id = 777000000000000003
        await cog.on_message(dis_msg2)
        rows = [r for r in await bump_db.get_guild_waitlist(guild) if r["service"] == "disboard"]
        check("disboard cooldown guard holds", len(rows) == 1, f"got {len(rows)}")

        # -- Carl failure message adds nobody --
        fail_msg = make_message(
            author_id=CARL_BOT_ID,
            content="You have to wait 3 hours before you can bump this server again!",
            application_id=CARL_BOT_ID,
            guild_id=guild,
        )
        fail_msg.id = 777000000000000004
        await cog.on_message(fail_msg)
        rows = [r for r in await bump_db.get_guild_waitlist(guild) if r["service"] == "carl"]
        check("carl failure message ignored", len(rows) == 1, f"got {len(rows)}")

        # -- Unrelated message ignored entirely --
        other = make_message(author_id=424242424242424242, content="hello world")
        other.id = 777000000000000005
        await cog.on_message(other)
        check("unrelated message ignored", len(await bump_db.get_guild_waitlist(guild)) == 2)


async def test_restart_persistence():
    """Entry written by one process is found and pinged by the next process.

    Simulates: bump happens -> bot restarts -> scheduler reloads pending
    cooldowns from SQLite and delivers the (now overdue) ping exactly once.
    """
    print("\n[7] Restart persistence (cross-process)")
    guild = 444444444444444444
    user = 123456789012345678
    channel_id = 123456789012345678

    # "Process 1": bot records a Carl bump then exits (crash/restart).
    proc1 = (
        "import os, sys\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(PROJECT_ROOT)!r})\n"
        f"os.environ.setdefault('DISCORD_TOKEN', 'test-token-not-real')\n"
        "import config\n"
        f"config.Config.DATA_DIR = Path({str(_tmp_dir)!r})\n"
        "import asyncio\n"
        "from datetime import datetime, timedelta, timezone\n"
        "from bot.database import bump_db\n"
        "async def main():\n"
        "    await bump_db.init_db()\n"
        "    now = datetime.now(timezone.utc)\n"
        f"    await bump_db.add_to_waitlist({guild}, {user}, 'carl', int((now - timedelta(seconds=5)).timestamp()))\n"
        "asyncio.run(main())\n"
    )
    r = await asyncio.create_subprocess_exec(
        sys.executable, "-c", proc1,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await r.communicate()
    check("process 1 wrote entry", r.returncode == 0, err.decode()[:200])

    # "Process 2" (this one): after restart, entry is still due and delivered.
    rows = await bump_db.get_guild_waitlist(guild)
    check("entry survived restart", len(rows) == 1, f"got {len(rows)}")
    due = await bump_db.get_due_waitlist()
    check("expired entry is due after restart", any(e["guild_id"] == guild for e in due))

    await bump_db.update_guild_settings(guild, notification_channel_id=channel_id)
    sent = []

    async def fake_send(*args, **kwargs):
        sent.append(kwargs.get("content", args[0] if args else ""))

    channel = MagicMock()
    channel.id = channel_id
    channel.send = fake_send
    channel.guild = SimpleNamespace(me=SimpleNamespace(id=111))
    channel.permissions_for = lambda _me: SimpleNamespace(send_messages=True)
    channel.mention = f"<#{channel_id}>"

    bot = MagicMock()
    bot.get_channel = lambda _cid: channel if _cid == channel_id else None

    scheduler = BumpScheduler(bot)
    await scheduler._check_and_ping()
    check("overdue ping delivered after restart", len(sent) == 1, f"sent={sent}")
    check("entry removed after restart delivery", len(await bump_db.get_guild_waitlist(guild)) == 0)

    # Second pass: no duplicate notification.
    await scheduler._check_and_ping()
    check("no duplicate after restart", len(sent) == 1)


async def test_identity_retry():
    """A bump whose bumper can't be identified is queued and later repaired.

    Mirrors the live bug: the cached confirmation carries no interaction
    metadata, so nobody lands on the waitlist even though the bump counted.
    A fresh fetch (as the retry loop does) finds the invoking user.
    """
    print("\n[8] Identity retry for unidentified bumpers")
    await bump_db.init_db()
    guild = 555555555555555555
    user = 123456789012345678
    channel_id = 123456789012345678

    cog = BumpCog(MagicMock())
    cog.bot.get_user = lambda uid: SimpleNamespace(id=uid)

    async def ok(guild_id):
        return True

    with patch("bot.cogs.bump.is_guild_enabled", ok):
        # Confirmation with NO identifiable bumper anywhere.
        orphan = make_message(
            author_id=CARL_BOT_ID,
            content="You've successfully bumped this server, it is now ranked 530 out of 24120 servers!",
            application_id=CARL_BOT_ID,
            guild_id=guild,
        )
        orphan.id = 888000000000000001
        await cog.on_message(orphan)

        rows = await bump_db.get_guild_waitlist(guild)
        check("unidentified bump adds nobody to waitlist", len(rows) == 0, str(rows))

        pending = await bump_db.get_pending_bumpers()
        check("unidentified bump queued for retry", len(pending) == 1, str(pending))
        if pending:
            check("queued row keeps service + ping time", pending[0]["service"] == "carl" and pending[0]["ping_at"] > 0)

        # The queue is idempotent (backfill can't double-queue).
        await bump_db.add_pending_bumper(guild, orphan.id, "carl", 123)
        pending = await bump_db.get_pending_bumpers()
        check("re-queueing same message is a no-op", len(pending) == 1, str(len(pending)))

        # Retry pass: fresh fetch now carries the interaction user, exactly
        # like the live diagnostic command that proved it for orange's bump.
        def fetch_message(msg_id):
            repaired = make_message(
                author_id=CARL_BOT_ID,
                content="You've successfully bumped this server, it is now ranked 530 out of 24120 servers!",
                application_id=CARL_BOT_ID,
                interaction_user_id=user,
                guild_id=guild,
            )
            repaired.id = msg_id
            return repaired

        async def fetch_message_async(msg_id):
            return fetch_message(msg_id)

        channel = MagicMock()
        channel.id = channel_id
        channel.fetch_message = fetch_message_async
        cog.bot.get_channel = lambda cid: channel if cid == channel_id else None
        cog.bot.get_guild = lambda gid: None

        await cog._repair_pending_bumpers()

        rows = await bump_db.get_guild_waitlist(guild)
        check("retry resolved the bumper onto the waitlist", len(rows) == 1, str(rows))
        if rows:
            check("repaired row is for the right user + service", rows[0]["user_id"] == user and rows[0]["service"] == "carl")
        check("queue empty after resolution", len(await bump_db.get_pending_bumpers()) == 0)

        # Retry pass again: no duplicate waitlist rows.
        await cog._repair_pending_bumpers()
        check("no duplicate after second pass", len(await bump_db.get_guild_waitlist(guild)) == 1)


async def test_restart_bumper_repair():
    """Restart scenario: the last confirmation before a restart can't be
    reprocessed (duplicate message id) and its bumper is missing from the
    waitlist. Backfill must repair it WITHOUT resurrecting pings that were
    already delivered before the restart.
    """
    print("\n[9] Restart: missed bumper repaired, delivered ping not resurrected")
    await bump_db.init_db()
    guild = 666666666666666666
    user = 123456789012345678
    now = datetime.now(timezone.utc)

    cog = BumpCog(MagicMock())

    # Confirmation from 1h ago (4h left on the 6h Carl cooldown) whose bumper
    # was never recorded because the bot restarted right after recording it.
    msg = make_message(
        author_id=CARL_BOT_ID,
        content="You've successfully bumped this server, it is now ranked 531 out of 24120 servers!",
        application_id=CARL_BOT_ID,
        interaction_user_id=user,
        guild_id=guild,
    )
    msg.created_at = now - timedelta(hours=1)
    msg.id = 999000000000000001

    # Backfill calls on_message; make the guild enabled.
    with patch("bot.cogs.bump.is_guild_enabled", lambda gid: asyncio.sleep(0, True)):
        # The message was already counted before the restart -> on_message
        # must skip it (at/before last recorded bump). Pre-seed that state.
        await bump_db.record_successful_bump(guild, "carl", msg.created_at)
        await bump_db.mark_bump_message_seen(guild, "carl", msg.id)

        repaired = await cog._repair_backfill_message(msg)
        check("backfill repaired the missed bumper", repaired is True)

        rows = await bump_db.get_guild_waitlist(guild)
        check("repaired waitlist row has correct cooldown", len(rows) == 1 and abs(rows[0]["ping_at"] - int((msg.created_at + timedelta(hours=6)).timestamp())) < 5, str(rows))

        # Second backfill of the same message must not duplicate the row.
        repaired_again = await cog._repair_backfill_message(msg)
        check("second backfill pass adds no duplicate", repaired_again is False)
        check("waitlist still has exactly one row", len(await bump_db.get_guild_waitlist(guild)) == 1)

        # An ALREADY-DELIVERED window (confirmation 7h old) must never be
        # resurrected.
        old_msg = make_message(
            author_id=CARL_BOT_ID,
            content="You've successfully bumped this server, it is now ranked 532 out of 24120 servers!",
            application_id=CARL_BOT_ID,
            interaction_user_id=user,
            guild_id=guild,
        )
        old_msg.created_at = now - timedelta(hours=7)
        old_msg.id = 999000000000000002
        await bump_db.record_successful_bump(guild, "carl", old_msg.created_at)
        await bump_db.mark_bump_message_seen(guild, "carl", old_msg.id)
        repaired_old = await cog._repair_backfill_message(old_msg)
        check("delivered window not resurrected", repaired_old is False)
        check("waitlist unchanged by stale confirmation", len(await bump_db.get_guild_waitlist(guild)) == 1)


async def test_backfill_ignores_failures():
    """Backfill repair must only credit successful bumps. Seen live on the
    Oracle server: a restart backfill added a phantom waitlist entry from a
    Carl-bot "You're on cooldown" FAILURE notice, because the repair path
    never checked the detection result."""
    print("\n[10] Backfill repair ignores cooldown/failure notices")
    await bump_db.init_db()
    guild = 777777777777777777
    user = 123456789012345678
    now = datetime.now(timezone.utc)

    cog = BumpCog(MagicMock())
    cog.bot.get_user = lambda uid: SimpleNamespace(id=uid)

    # Real-looking cooldown failure: bot identity + invoking user, no success
    # phrase - exactly what Carl-bot posts to a second bumper.
    failure = make_message(
        author_id=CARL_BOT_ID,
        content="You're on cooldown, you can bump this server again <t:1789125653:R>",
        application_id=CARL_BOT_ID,
        interaction_user_id=user,
        guild_id=guild,
    )
    failure.created_at = now - timedelta(minutes=5)
    failure.id = 777000000000000001

    with patch("bot.cogs.bump.is_guild_enabled", lambda gid: asyncio.sleep(0, True)):
        repaired = await cog._repair_backfill_message(failure)
        check("failure notice repairs nobody", repaired is False)
        check("failure notice adds no waitlist row", len(await bump_db.get_guild_waitlist(guild)) == 0)

        # Sanity: a genuine success from the same user still repairs fine.
        success = make_message(
            author_id=CARL_BOT_ID,
            content="You've successfully bumped this server, it is now ranked 533 out of 24120 servers!",
            application_id=CARL_BOT_ID,
            interaction_user_id=user,
            guild_id=guild,
        )
        success.created_at = now - timedelta(minutes=5)
        success.id = 777000000000000002
        repaired = await cog._repair_backfill_message(success)
        check("genuine success still repairs", repaired is True)
        rows = await bump_db.get_guild_waitlist(guild)
        check("success repair lands on waitlist", len(rows) == 1 and rows[0]["user_id"] == user, str(rows))


async def test_scan_repairs_blank_confirmation():
    """Live-gap scenario (seen for cats.dev on 2026-09-11): the confirmation's
    MESSAGE_CREATE arrives but under-hydrated - blank content, no embeds - so
    detection sees no success phrase and drops it silently. The periodic scan
    must credit it on its next pass via a fresh history fetch."""
    print("\n[11] Periodic scan repairs blank (under-hydrated) confirmation")
    await bump_db.init_db()
    guild = 888888888888888888
    user = 123456789012345678

    cog = BumpCog(MagicMock())
    cog.bot.get_user = lambda uid: SimpleNamespace(id=uid)

    # What the gateway delivered: blank content, no interaction metadata.
    blank = make_message(
        author_id=CARL_BOT_ID,
        content="",
        application_id=CARL_BOT_ID,
        guild_id=guild,
    )
    blank.created_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    blank.id = 888111000000000001

    with patch("bot.cogs.bump.is_guild_enabled", lambda gid: asyncio.sleep(0, True)):
        await bump_db.update_guild_settings(guild, notification_channel_id=123456789012345678)

        # The live path finds nothing to do.
        await cog.on_message(blank)
        check("blank confirmation adds nobody live", len(await bump_db.get_guild_waitlist(guild)) == 0)

        # One minute later the scan re-reads history - now fully hydrated,
        # exactly what a fresh fetch of the same message returns.
        hydrated = make_message(
            author_id=CARL_BOT_ID,
            content="You've successfully bumped this server, it is now ranked 534 out of 24274 servers!",
            application_id=CARL_BOT_ID,
            interaction_user_id=user,
            guild_id=guild,
        )
        hydrated.created_at = blank.created_at
        hydrated.id = blank.id

        channel = MagicMock()
        channel.id = 123456789012345678
        async def history(limit=None):
            yield hydrated
        channel.history = history
        guild_obj = MagicMock()
        guild_obj.id = guild
        guild_obj.get_channel = lambda cid: channel if cid == channel.id else None
        cog.bot.guilds = [guild_obj]

        await cog._scan_recent_confirmations()

        rows = await bump_db.get_guild_waitlist(guild)
        check("scan credited the blank confirmation", len(rows) == 1 and rows[0]["user_id"] == user, str(rows))

        # Second pass: history replay returns the same message; the seen-set
        # must keep it from being processed again.
        async def history2(limit=None):
            yield hydrated
        channel.history = history2
        await cog._scan_recent_confirmations()
        check("scan pass is idempotent", len(await bump_db.get_guild_waitlist(guild)) == 1)


def test_debug_dump():
    print("\n[5] Debug diagnostics")
    msg = make_message(
        author_id=CARL_BOT_ID,
        content="You've successfully bumped this server, it is now ranked 528 out of 24120 servers!",
        application_id=CARL_BOT_ID,
        interaction_user_id=123456789012345678,
        webhook_id=None,
    )
    info = debug_bump_detection(msg)
    for key in (
        "author_id", "application_id", "webhook_id", "message_type",
        "channel_id", "guild_id", "content", "interaction_user_id",
    ):
        check(f"debug has {key}", key in info)
    check("debug detects carl success", info["carl_success"] is True)
    check("debug shows invoking user", info["interaction_user_id"] == 123456789012345678)


async def main():
    await test_carl()
    await test_disboard()
    await test_db_flow()
    await test_notifications_disabled()
    test_debug_dump()
    await test_on_message_pipeline()
    await test_restart_persistence()
    await test_identity_retry()
    await test_restart_bumper_repair()
    await test_backfill_ignores_failures()
    await test_scan_repairs_blank_confirmation()

    print(f"\n{'=' * 50}")
    print(f"TOTAL: {PASS} passed, {FAIL} failed")
    if FAIL:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
