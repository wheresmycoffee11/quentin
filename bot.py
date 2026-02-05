import os
import sqlite3
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
ZOOM_LINK = "https://us06web.zoom.us/j/81195928527?pwd=I4fhjlHpuE8r4KiGGSTuiggcNiq5TF.1"
CALENDAR_LINK = "https://calendar.google.com/calendar/event?action=TEMPLATE&tmeid=NzRscWFyNzQ2Mms1MXYzcGI1YTJqZHFlaDBfMjAyNjAxMjJUMTcwMDAwWiBjXzI2YjE0MmU5Njc3YzYzMWNhODUzYjBkMDJjYTRjZWZmNTMzNzhkOWE3YzczOTJjYzRkNTAxMmExODEzMjE2ZTlAZw&tmsrc=c_26b142e9677c631ca853b0d02ca4ceff53378d9a7c7392cc4d5012a1813216e9%40group.calendar.google.com&scp=ALL"
CHANNEL_NAME = "weekly-calls"
ADMIN_USER_ID = os.environ.get("ADMIN_USER_ID")  # Your Slack user ID
TIMEZONE = ZoneInfo("America/New_York")

# Initialize the app with Socket Mode
app = App(token=os.environ.get("SLACK_BOT_TOKEN"))

# Database setup
def init_db():
    """Initialize SQLite database for storing topics."""
    conn = sqlite3.connect("topics.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            user_name TEXT,
            topic TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            week_of TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notified_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            week_of TEXT NOT NULL,
            notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, week_of)
        )
    """)
    conn.commit()
    conn.close()

def get_current_week():
    """Get the week identifier (Monday of current week) for grouping topics."""
    now = datetime.now(TIMEZONE)
    monday = now - timedelta(days=now.weekday())
    return monday.strftime("%Y-%m-%d")

def get_channel_id_by_name(client, channel_name):
    """Find channel ID by name."""
    try:
        result = client.conversations_list(types="public_channel,private_channel")
        for channel in result["channels"]:
            if channel["name"] == channel_name:
                return channel["id"]
    except Exception as e:
        logger.error(f"Error finding channel: {e}")
    return None

def user_already_notified(user_id, week_of):
    """Check if user was already notified this week."""
    conn = sqlite3.connect("topics.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM notified_users WHERE user_id = ? AND week_of = ?",
        (user_id, week_of)
    )
    result = cursor.fetchone()
    conn.close()
    return result is not None

def mark_user_notified(user_id, week_of):
    """Mark that user has been notified this week."""
    conn = sqlite3.connect("topics.db")
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO notified_users (user_id, week_of) VALUES (?, ?)",
            (user_id, week_of)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # Already notified
    conn.close()

def save_topic(user_id, user_name, topic):
    """Save a topic to the database."""
    conn = sqlite3.connect("topics.db")
    cursor = conn.cursor()
    week_of = get_current_week()
    cursor.execute(
        "INSERT INTO topics (user_id, user_name, topic, week_of) VALUES (?, ?, ?, ?)",
        (user_id, user_name, topic, week_of)
    )
    conn.commit()
    conn.close()

def get_topics_for_week():
    """Get all topics for the current week."""
    conn = sqlite3.connect("topics.db")
    cursor = conn.cursor()
    week_of = get_current_week()
    cursor.execute(
        "SELECT user_name, topic, created_at FROM topics WHERE week_of = ? ORDER BY created_at",
        (week_of,)
    )
    results = cursor.fetchall()
    conn.close()
    return results

def clear_week_data():
    """Clear data for the current week (call after the meeting)."""
    conn = sqlite3.connect("topics.db")
    cursor = conn.cursor()
    week_of = get_current_week()
    cursor.execute("DELETE FROM topics WHERE week_of = ?", (week_of,))
    cursor.execute("DELETE FROM notified_users WHERE week_of = ?", (week_of,))
    conn.commit()
    conn.close()


def get_meeting_phase():
    """Determine where we are relative to the Thursday meeting.

    Returns one of:
      'before_reminder' - not Thursday, or before Thu 11 AM, or after Thu 2 PM
                          (data is cleared at 2 PM so new reactions work for next week)
      'after_reminder'  - Thursday 11 AM to 12 PM (call starts soon, include Zoom link)
      'live'            - Thursday 12 PM to 1 PM (call is live)
      'after_call'      - Thursday 1 PM to 2 PM (call just ended, cleanup pending)
    """
    now = datetime.now(TIMEZONE)
    if now.weekday() != 3:  # Not Thursday
        return "before_reminder"
    hour = now.hour
    if hour < 11:
        return "before_reminder"
    elif hour < 12:
        return "after_reminder"
    elif hour < 13:
        return "live"
    elif hour < 14:
        return "after_call"
    else:
        # After 2 PM cleanup — back to normal so next week's reactions work
        return "before_reminder"


def build_invite_message(first_name, phase):
    """Build the appropriate DM based on the current meeting phase."""
    if phase == "live":
        return f"""Hey {first_name}!

The weekly call is *live right now*! Jump in:

*Join the call:* <{ZOOM_LINK}|Click here to join on Zoom>

If you have a topic you'd like to bring up, just reply here and I'll pass it along to Chris!"""

    elif phase == "after_reminder":
        return f"""Hey {first_name}!

Thanks for raising your hand for the weekly call!

The call starts *today at 12:00 PM EST* — that's less than an hour away!

*Join the call:* <{ZOOM_LINK}|Click here to join on Zoom>

Is there anything specific you'd like to discuss on the call? Just reply here and I'll make sure Chris sees it before the session!"""

    else:  # before_reminder
        return f"""Hey {first_name}!

Thanks for raising your hand for the weekly call!

The call is *Thursday at 12:00 PM EST*.

I'll send you a reminder with the Zoom link 1 hour before the call.

---

Is there anything specific you'd like to discuss on the call? Just reply here and I'll make sure Chris sees it before the session!"""


# Event handler for reaction_added
@app.event("reaction_added")
def handle_raised_hand(client, event, logger):
    """Handle when someone adds a raised hand emoji."""
    logger.info(f"Reaction event received: {event}")

    reaction = event.get("reaction", "")
    user_id = event.get("user")
    item = event.get("item", {})
    channel_id = item.get("channel")

    logger.info(f"Reaction: {reaction}, User: {user_id}, Channel: {channel_id}")

    # Check if it's a raised hand emoji (various forms)
    # Use startswith to catch skin tone variations like "hand::skin-tone-2"
    raised_hand_emojis = ["raised_hand", "hand", "raising_hand", "raised_hands", "raised_back_of_hand"]
    is_raised_hand = any(reaction.startswith(emoji) for emoji in raised_hand_emojis)

    if not is_raised_hand:
        logger.info(f"Reaction '{reaction}' not a raised hand emoji, ignoring")
        return

    # Verify it's in the correct channel
    try:
        channel_info = client.conversations_info(channel=channel_id)
        channel_name = channel_info["channel"]["name"]
        if channel_name != CHANNEL_NAME:
            return
    except Exception as e:
        logger.error(f"Error checking channel: {e}")
        return

    week_of = get_current_week()
    phase = get_meeting_phase()

    # Check if already notified this week
    if user_already_notified(user_id, week_of):
        logger.info(f"User {user_id} already notified this week, skipping")
        return

    # After the call is over, don't send anything
    if phase == "after_call":
        logger.info(f"Call is over for this week, ignoring reaction from {user_id}")
        return

    # Get user info for a friendly greeting
    try:
        user_info = client.users_info(user=user_id)
        user_name = user_info["user"]["real_name"] or user_info["user"]["name"]
        first_name = user_name.split()[0] if user_name else "there"
    except Exception as e:
        logger.error(f"Error getting user info: {e}")
        first_name = "there"
        user_name = "Unknown"

    # Send DM to the user with phase-appropriate message
    try:
        dm_message = build_invite_message(first_name, phase)

        client.chat_postMessage(
            channel=user_id,  # DM by sending to user_id
            text=dm_message
        )

        mark_user_notified(user_id, week_of)
        logger.info(f"Sent DM to {user_name} ({user_id}) [phase={phase}]")

    except Exception as e:
        logger.error(f"Error sending DM to {user_id}: {e}")


# Handle DM responses (topic submissions)
@app.event("message")
def handle_dm_response(client, event, logger):
    """Handle when someone responds in DM with a topic."""
    # Only process direct messages (im)
    channel_type = event.get("channel_type")
    if channel_type != "im":
        return

    # Ignore bot messages
    if event.get("bot_id") or event.get("subtype"):
        return

    user_id = event.get("user")
    text = event.get("text", "").strip()

    if not text:
        return

    week_of = get_current_week()
    phase = get_meeting_phase()

    # Get user name
    try:
        user_info = client.users_info(user=user_id)
        user_name = user_info["user"]["real_name"] or user_info["user"]["name"]
        first_name = user_name.split()[0] if user_name else "there"
    except:
        user_name = "Unknown"
        first_name = "there"

    # If they haven't been notified yet, treat this DM as them wanting to join
    if not user_already_notified(user_id, week_of):
        if phase == "after_call":
            try:
                client.chat_postMessage(
                    channel=user_id,
                    text=f"Hey {first_name}! The call already wrapped up for this week. Keep an eye on #{CHANNEL_NAME} for next week's announcement!"
                )
            except Exception as e:
                logger.error(f"Error sending after-call message to {user_id}: {e}")
            return

        # Send them the invite message and mark them as notified
        try:
            dm_message = build_invite_message(first_name, phase)
            client.chat_postMessage(channel=user_id, text=dm_message)
            mark_user_notified(user_id, week_of)
            logger.info(f"New user {user_name} messaged in — sent invite [phase={phase}]")
        except Exception as e:
            logger.error(f"Error sending invite to {user_id}: {e}")

        # Also save their message as a topic
        save_topic(user_id, user_name, text)
        logger.info(f"Saved topic from new user {user_name}: {text[:50]}...")
        return

    # Already notified — save topic as before
    save_topic(user_id, user_name, text)

    # Confirm receipt
    try:
        client.chat_postMessage(
            channel=user_id,
            text="Got it! I've noted that down. Chris will see it before the call. See you Thursday!"
        )
        logger.info(f"Saved topic from {user_name}: {text[:50]}...")
    except Exception as e:
        logger.error(f"Error confirming topic receipt: {e}")


def send_consolidated_topics():
    """Send consolidated topics to admin 1 hour before the call."""
    if not ADMIN_USER_ID:
        logger.error("ADMIN_USER_ID not set, can't send consolidated topics")
        return

    topics = get_topics_for_week()

    if not topics:
        message = """*Weekly Call Topics Update*

No topics were submitted this week. You're going in fresh!

The call starts in 1 hour."""
    else:
        topic_list = "\n\n".join([
            f"*{name}*: {topic}"
            for name, topic, _ in topics
        ])

        message = f"""*Weekly Call Topics Update*

Here's what people want to discuss today:

{topic_list}

---
The call starts in 1 hour. {len(topics)} topic(s) submitted."""

    try:
        app.client.chat_postMessage(
            channel=ADMIN_USER_ID,
            text=message
        )
        logger.info("Sent consolidated topics to admin")
    except Exception as e:
        logger.error(f"Error sending consolidated topics: {e}")


def send_reminders():
    """Send reminder to all participants 1 hour before the call."""
    conn = sqlite3.connect("topics.db")
    cursor = conn.cursor()
    week_of = get_current_week()

    # Get all users who raised their hand this week
    cursor.execute(
        "SELECT user_id FROM notified_users WHERE week_of = ?",
        (week_of,)
    )
    users = cursor.fetchall()
    conn.close()

    if not users:
        logger.info("No participants to remind this week")
        return

    reminder_message = f"""Hey! This is your reminder that the weekly call starts in 1 hour.

*Join the call:* <{ZOOM_LINK}|Click here to join on Zoom>

*Time:* Thursday at 12:00 PM EST (starting in 1 hour)

See you soon!"""

    sent_count = 0
    for (user_id,) in users:
        try:
            app.client.chat_postMessage(
                channel=user_id,
                text=reminder_message
            )
            sent_count += 1
        except Exception as e:
            logger.error(f"Error sending reminder to {user_id}: {e}")

    logger.info(f"Sent reminders to {sent_count} participant(s)")


def clear_after_call():
    """Clear the week's data after the call (runs Thursday at 2 PM EST)."""
    clear_week_data()
    logger.info("Cleared week data after call")


def weekly_reset():
    """Reset all data for the new week (runs Sunday at midnight)."""
    conn = sqlite3.connect("topics.db")
    cursor = conn.cursor()
    # Clear all topics and notified users to start fresh for the new week
    cursor.execute("DELETE FROM topics")
    cursor.execute("DELETE FROM notified_users")
    conn.commit()
    conn.close()
    logger.info("Weekly reset complete - all data cleared for new week")


# Initialize scheduler
scheduler = BackgroundScheduler(timezone=TIMEZONE)

# Schedule consolidated topics - Thursday at 11:00 AM EST (1 hour before noon call)
scheduler.add_job(
    send_consolidated_topics,
    CronTrigger(day_of_week="thu", hour=11, minute=0, timezone=TIMEZONE),
    id="send_topics",
    replace_existing=True
)

# Schedule participant reminders - Thursday at 11:00 AM EST (1 hour before noon call)
scheduler.add_job(
    send_reminders,
    CronTrigger(day_of_week="thu", hour=11, minute=0, timezone=TIMEZONE),
    id="send_reminders",
    replace_existing=True
)

# Schedule cleanup - Thursday at 2:00 PM EST (after the call)
scheduler.add_job(
    clear_after_call,
    CronTrigger(day_of_week="thu", hour=14, minute=0, timezone=TIMEZONE),
    id="clear_data",
    replace_existing=True
)

# Schedule weekly reset - Sunday at 12:01 AM EST (fresh start for new week)
scheduler.add_job(
    weekly_reset,
    CronTrigger(day_of_week="sun", hour=0, minute=1, timezone=TIMEZONE),
    id="weekly_reset",
    replace_existing=True
)


if __name__ == "__main__":
    # Initialize database
    init_db()

    # Start the scheduler
    scheduler.start()
    logger.info("Scheduler started")

    # Start the app with Socket Mode
    handler = SocketModeHandler(
        app,
        os.environ.get("SLACK_APP_TOKEN")
    )
    logger.info("Bot starting...")
    handler.start()
