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

    # Simulate restart: the DB file is on disk; entries must still be there.
    rows = await bump_db.get_guild_waitlist(guild)
    check("entries persist (restart survival)", len(rows) == 2)

    # Nothing is due yet.
    due = await bump_db.get_due_waitlist()
    check("nothing due yet", len(due) == 0, f"got {len(due)}")

    # Make entries due and run the scheduler with a mock channel.
    await bump_db.add_to_waitlist(guild, user, "carl", int((now - timedelta(seconds=1)).timestamp()))
    await bump_db.add_to_waitlist(guild, user, "disboard", int((now - timedelta(seconds=1)).timestamp()))

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

    print(f"\n{'=' * 50}")
    print(f"TOTAL: {PASS} passed, {FAIL} failed")
    if FAIL:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
