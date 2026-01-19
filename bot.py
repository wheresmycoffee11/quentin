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
    raised_hand_emojis = ["raised_hand", "hand", "raising_hand", "raised_hands"]
    if reaction not in raised_hand_emojis:
        logger.info(f"Reaction '{reaction}' not in raised hand list, ignoring")
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

    # Check if already notified this week
    if user_already_notified(user_id, week_of):
        logger.info(f"User {user_id} already notified this week, skipping")
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

    # Send DM to the user
    try:
        dm_message = f"""Hey {first_name}!

Thanks for raising your hand for the weekly call!

The call is *Thursday at 12:00 PM EST*.

I'll send you a reminder with the Zoom link 1 hour before the call.

---

Is there anything specific you'd like to discuss on the call? Just reply here and I'll make sure Chris sees it before the session!"""

        client.chat_postMessage(
            channel=user_id,  # DM by sending to user_id
            text=dm_message
        )

        mark_user_notified(user_id, week_of)
        logger.info(f"Sent DM to {user_name} ({user_id})")

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

    # Only save if they were notified (meaning they raised their hand)
    if not user_already_notified(user_id, week_of):
        # They're just messaging the bot without raising hand, could add handling here
        return

    # Get user name
    try:
        user_info = client.users_info(user=user_id)
        user_name = user_info["user"]["real_name"] or user_info["user"]["name"]
    except:
        user_name = "Unknown"

    # Save the topic
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
