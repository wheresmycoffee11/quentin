# Quentin - The QA Call Helper

A Slack bot that helps manage weekly call attendance and topic collection.

## What it does

1. Monitors the `#weekly-calls` channel for raised hand emoji reactions
2. Sends a DM to users who raise their hand with Zoom link and calendar invite
3. Collects discussion topics from user replies
4. Sends consolidated topics to the admin 1 hour before the call (Thursday 11 AM EST)
5. Clears data after the call (Thursday 2 PM EST)

## Slack App Setup

### 1. Create a new Slack App

1. Go to https://api.slack.com/apps
2. Click "Create New App" > "From scratch"
3. Name it "Quentin" (or whatever you prefer)
4. Select your workspace

### 2. Enable Socket Mode

1. Go to "Socket Mode" in the left sidebar
2. Toggle "Enable Socket Mode" ON
3. Create an app-level token with `connections:write` scope
4. Copy the token (starts with `xapp-`) - this is your `SLACK_APP_TOKEN`

### 3. Configure Bot Token Scopes

Go to "OAuth & Permissions" and add these **Bot Token Scopes**:

- `channels:read` - View basic channel info
- `chat:write` - Send messages
- `groups:read` - View private channels the bot is in
- `im:history` - View DM history
- `im:write` - Send DMs
- `reactions:read` - View reactions
- `users:read` - View user info

### 4. Enable Events

Go to "Event Subscriptions":

1. Toggle "Enable Events" ON
2. Under "Subscribe to bot events", add:
   - `message.im` - Listen for DMs
   - `reaction_added` - Listen for emoji reactions

### 5. Install the App

1. Go to "Install App" in the left sidebar
2. Click "Install to Workspace"
3. Copy the "Bot User OAuth Token" (starts with `xoxb-`) - this is your `SLACK_BOT_TOKEN`

### 6. Get Your User ID

1. In Slack, click on your profile picture
2. Click "Profile"
3. Click the three dots (More actions)
4. Click "Copy member ID"
5. This is your `ADMIN_USER_ID`

### 7. Invite the Bot

Invite the bot to your `#weekly-calls` channel:
```
/invite @Quentin
```

## Local Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your tokens

# Run the bot
python bot.py
```

## Configuration

Edit these values in `bot.py` to customize:

- `ZOOM_LINK` - Your Zoom meeting link
- `CALENDAR_LINK` - Google Calendar event link
- `CHANNEL_NAME` - Channel to monitor (default: "weekly-calls")
- `TIMEZONE` - Timezone for scheduling (default: America/New_York)

The scheduler is set for:
- **11:00 AM EST Thursday** - Send topics to admin
- **2:00 PM EST Thursday** - Clear week's data

## Running in Production

For production, consider using a process manager like `systemd` or running in Docker.

### Using systemd (Linux)

Create `/etc/systemd/system/quentin-bot.service`:

```ini
[Unit]
Description=Quentin Slack Bot
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/bot
Environment="SLACK_BOT_TOKEN=xoxb-..."
Environment="SLACK_APP_TOKEN=xapp-..."
Environment="ADMIN_USER_ID=U..."
ExecStart=/path/to/venv/bin/python bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable quentin-bot
sudo systemctl start quentin-bot
```
