# RLCS Tournament Notification Bot

Telegram bot that notifies you about upcoming Rocket League Championship Series (RLCS) tournaments. Data sourced from [Liquipedia](https://liquipedia.net/rocketleague/Liquipedia:RLCS_Events).

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and get your token.
2. Find your Telegram user ID (e.g. with [@userinfobot](https://t.me/userinfobot)).
3. Copy `.env.example` to `.env` and fill in:

```ini
TELEGRAM_BOT_TOKEN=your-token-here
ALLOWED_USER_IDS=your-user-id
NOTIFY_DAYS_AHEAD=1
```

4. Install dependencies and run:

```bash
uv sync
uv run python main.py
```

## Development

```bash
uv sync --dev
uv run pre-commit install
```

Pre-commit runs Ruff linter and formatter on every commit. To run on all files:

```bash
uv run pre-commit run --all-files
```

## Commands

| Command | Description |
|---|---|
| `/start` / `/help` | Welcome and available commands |
| `/next` | Next upcoming RLCS tournament |
| `/schedule` | All upcoming RLCS tournaments grouped by type |
| `/refresh` | Force-reload tournament data from Liquipedia |

## Notifications

The bot polls Liquipedia every `POLL_INTERVAL_MINUTES` (default 60). When a tournament is starting within `NOTIFY_DAYS_AHEAD` days, it sends a notification with event details and a "Ver en Liquipedia" link. A tournament is recorded as announced (in `<STATE_DIR>/announced.json`) only after the message is successfully delivered, so a missing chat or a transient failure does not permanently suppress it.

The bot can only push to chats it knows about. Any authorized interaction (e.g. `/next`, `/start`) registers your chat in `<STATE_DIR>/user_chats.json`. Keep `STATE_DIR` on a persistent volume so this survives restarts — the included `deploy.sh` mounts the `rlbot-data` Docker volume at `/app/state` for this.

## Configuration

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | — | Bot token from @BotFather |
| `ALLOWED_USER_IDS` | Yes | — | Comma-separated Telegram user IDs |
| `NOTIFY_DAYS_AHEAD` | Yes | — | Days before an event to send notification |
| `POLL_INTERVAL_MINUTES` | No | 60 | How often to check Liquipedia |
| `STATE_DIR` | No | `state` | Directory for persisted state (`announced.json`, `user_chats.json`) |
| `LOG_LEVEL` | No | INFO | Logging level |
| `LOG_FILE` | No | `logs/rlbot_<date>.log` | Log file path |

## Project Structure

```
rltournamentbot/
├── config.py       # Config dataclass + env loading
├── logger.py       # Logging setup (stdout + rotating file)
├── models.py       # Tournament dataclass
├── liquipedia.py   # MediaWiki API client + BS4 HTML parser
└── bot.py          # Telegram handlers, auth, notifications, poll loop
main.py             # Entry point
data/               # Raw HTML snapshots from Liquipedia
```

## Data Source

Uses the [Liquipedia MediaWiki API](https://liquipedia.net/rocketleague/api.php) (free, no key) to fetch the [RLCS Events](https://liquipedia.net/rocketleague/Liquipedia:RLCS_Events) page. HTML is parsed with BeautifulSoup to extract tournament names, dates, regions, and Liquipedia URLs.

Raw responses are saved to `data/v{version}-{date}.html` for inspection and change tracking. If Liquipedia changes their page structure, bump `_RAW_HTML_VERSION` in `liquipedia.py`.
