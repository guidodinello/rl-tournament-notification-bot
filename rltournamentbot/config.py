import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from .logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LoggerConfig:
    level: str = "INFO"
    file: Path | None = field(default_factory=lambda: Path(f"logs/rlbot_{date.today()}.log"))


@dataclass(frozen=True, slots=True)
class Config:
    logger: LoggerConfig
    telegram_bot_token: str
    allowed_user_ids: frozenset[int]
    notify_days_ahead: int
    poll_interval_minutes: int = 60


def load_config() -> Config:
    load_dotenv(override=True)

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")

    raw_ids = os.getenv("ALLOWED_USER_IDS")
    if not raw_ids:
        raise ValueError("ALLOWED_USER_IDS is required")

    try:
        allowed = frozenset(int(uid.strip()) for uid in raw_ids.split(",") if uid.strip())
    except ValueError as e:
        raise ValueError(f"ALLOWED_USER_IDS must be comma-separated integers: {e}") from e

    if not allowed:
        raise ValueError("ALLOWED_USER_IDS must contain at least one user ID")

    raw_days = os.getenv("NOTIFY_DAYS_AHEAD")
    if not raw_days:
        raise ValueError("NOTIFY_DAYS_AHEAD is required")

    try:
        notify_days_ahead = int(raw_days)
    except ValueError as e:
        raise ValueError("NOTIFY_DAYS_AHEAD must be an integer") from e

    if notify_days_ahead < 0:
        raise ValueError("NOTIFY_DAYS_AHEAD must be a non-negative integer")

    raw_interval = os.getenv("POLL_INTERVAL_MINUTES", "60")
    try:
        poll_interval_minutes = int(raw_interval)
    except ValueError as e:
        raise ValueError("POLL_INTERVAL_MINUTES must be an integer") from e

    if poll_interval_minutes < 1:
        raise ValueError("POLL_INTERVAL_MINUTES must be at least 1")

    raw_log_level = os.getenv("LOG_LEVEL")
    raw_log_file = os.getenv("LOG_FILE")
    logger_config = LoggerConfig(
        **({"level": raw_log_level.upper()} if raw_log_level else {}),
        **({"file": Path(raw_log_file)} if raw_log_file else {}),
    )

    return Config(
        telegram_bot_token=token,
        allowed_user_ids=allowed,
        notify_days_ahead=notify_days_ahead,
        poll_interval_minutes=poll_interval_minutes,
        logger=logger_config,
    )
