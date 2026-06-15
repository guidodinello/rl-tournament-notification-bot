# RLCS Tournament Notification Bot — Implementation Plan

## Overview

A Telegram bot that notifies you of upcoming RLCS (Rocket League Championship Series) tournaments. Built with `python-telegram-bot` and the Liquipedia MediaWiki API.

## Stack

- **Language**: Python 3.14
- **Bot framework**: `python-telegram-bot` v21+ (async, long-polling)
- **Data source**: Liquipedia MediaWiki API (free, no key required)
- **HTML parsing**: BeautifulSoup + lxml
- **Async HTTP**: aiohttp

## Project Structure

```
rltournamentbot/
├── __init__.py           # empty
├── config.py             # Config dataclass + load_config() via dotenv
├── logger.py             # init_logging() + get_logger() + rotating file handler
├── models.py             # Tournament dataclass
├── liquipedia.py         # fetch_upcoming_tournaments() async (MediaWiki API + BS4)
└── bot.py                # handlers, build_application(), background poll task

main.py                   # entry point (parallel to knowledger's main.py)
pyproject.toml            # dependencies + ruff/pyright config
.env.example              # documented env vars template
.python-version           # 3.14.6 (already set)
README.md                 # setup and usage guide
docs/
└── implementation-plan.md # this file
```

## Dependencies

```toml
dependencies = [
    "python-telegram-bot>=21.0",
    "python-dotenv>=1.0",
    "aiohttp>=3.9",
    "beautifulsoup4>=4.12",
    "lxml",
]
```

## Configuration (Environment Variables)

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | — | Bot token from @BotFather |
| `ALLOWED_USER_IDS` | Yes | — | Comma-separated Telegram user IDs (access control) |
| `NOTIFY_DAYS_AHEAD` | Yes | — | How many days before an event to send notification |
| `POLL_INTERVAL_MINUTES` | No | 60 | How often to check Liquipedia for new tournaments |
| `LOG_FILE` | No | `logs/rlbot_<date>.log` | Path to log file |
| `LOG_LEVEL` | No | `INFO` | Logging level |

## Telegram Commands

| Command | Handler | Behavior |
|---|---|---|
| `/start` | `cmd_start` | Welcome message with instructions |
| `/help` | `cmd_help` | Same as `/start` |
| `/next` | `cmd_next` | Show next upcoming RLCS tournament |
| `/schedule` | `cmd_schedule` | List all upcoming RLCS events |
| `/refresh` | `cmd_refresh` | Force-reload from Liquipedia + retry queued notifications |

## Data Source: Liquipedia MediaWiki API

**Endpoint**: `https://liquipedia.net/rocketleague/api.php`

**Primary query**:
```
action=parse
page=Liquipedia:RLCS_Events
prop=text
format=json
```

Returns rendered HTML of the RLCS Events page, which contains structured tables listing all RLCS events with names, dates, and regions.

**Parsing strategy**:
1. Fetch the page HTML via the MediaWiki API
2. Use BeautifulSoup to locate tournament table rows
3. Extract per-row: tournament name, start date, end date, region
4. Parse dates with `dateutil` or `datetime`
5. Filter to keep only future events
6. Return list of `Tournament` dataclass instances

**Rate limiting**: 1 request per 2 seconds per Liquipedia TOS. The bot polls every 60 minutes — well within limits.

**Fallback**: The RLCS Events page may have minor structural changes between seasons. The parser should be resilient (class-based selectors, multiple fallback patterns).

## Tournament Data Model

```python
@dataclass(frozen=True, slots=True)
class Tournament:
    name: str
    start_date: date
    end_date: date
    region: str
    prize_pool: str | None
    liquipedia_url: str
```

## Bot Architecture

### Startup Flow (`main.py`)

```
main()
  └─ load_config()            # read .env, validate, return Config
  └─ init_logging()           # stdout + rotating file handler
  └─ asyncio.run(main_async(config))
       └─ build_application(config)  # create Application, register handlers
       └─ create background poll task
       └─ run polling loop
       └─ graceful shutdown on SIGTERM/SIGINT
```

### Auth Pattern

Same decorator-based approach as knowledger:

```python
@_require_auth
async def cmd_next(update: Update, context: CustomContext) -> None:
    ...
```

Checks `update.effective_user.id in config.allowed_user_ids`. Denies access if not whitelisted.

### Notification Flow (Background Poll Task)

```
poll_liquipedia()
  └─ await fetch_upcoming_tournaments()  # from liquipedia.py
  └─ for each tournament starting in ≤ NOTIFY_DAYS_AHEAD:
       └─ if tournament_id not in announced.json:
            └─ send Telegram message with event details
            └─ add tournament_id to announced.json
  └─ on failure: log error (notifications are best-effort)
```

### State Persistence

- **`announced.json`**: Tracks which tournament IDs have been announced to avoid duplicates across bot restarts. Same pattern as knowledger's `queue.py` (JSON file in CWD).

## Implementation Order

| Step | File | Description |
|---|---|---|
| 1 | `rltournamentbot/__init__.py` | Empty package marker |
| 2 | `rltournamentbot/models.py` | `Tournament` dataclass |
| 3 | `rltournamentbot/logger.py` | `init_logging()`, `get_logger()`, rotating file handler, httpx noise filter |
| 4 | `rltournamentbot/config.py` | Frozen `Config` dataclass + `load_config()` with dotenv + validation |
| 5 | `rltournamentbot/liquipedia.py` | `fetch_upcoming_tournaments()` — async MediaWiki API call + BS4 parsing |
| 6 | `rltournamentbot/bot.py` | All handlers (`cmd_start`, `cmd_next`, `cmd_schedule`, `cmd_refresh`), `build_application()`, background poll task, `@_require_auth` decorator |
| 7 | `main.py` | Entry point — load config, init logging, run async main loop |
| 8 | `pyproject.toml` | Rewrite with dependencies, ruff config, pyright config |
| 9 | `.env.example` | Documented env var template |
| 10 | `README.md` | Setup and usage guide |

## Patterns Borrowed from Knowledger

| Pattern | Knowledger | RL Bot |
|---|---|---|
| Config | Frozen dataclass + dotenv + validation | Same |
| Logger | `init_logging()` idempotent, rotating file, httpx filter | Same |
| Entry point | `main()` → `config` → `logging` → `asyncio.run(main_async())` | Same |
| Auth | `@_require_auth` decorator + `ALLOWED_USER_IDS` | Same |
| Bot factory | `build_application(config)` registers handlers | Same |
| Refresh | `/refresh` flushes queued items | Same |
| State | JSON file (`queue.py`) | `announced.json` for dedup |

## Key Differences from Knowledger

| Aspect | Knowledger | RL Bot |
|---|---|---|
| Platform | Telegram (knowledge bot) | Telegram (notification bot) |
| Trigger | User sends YouTube URL | Scheduled polling + manual commands |
| External API | Claude.ai (unofficial) + YouTube | Liquipedia MediaWiki API |
| Dependencies | curl-cffi, youtube-transcript-api | aiohttp, beautifulsoup4, lxml |
| State | Upload queue (petition_queue.json) | Announcement dedup (announced.json) |
