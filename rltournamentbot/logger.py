import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_SUPPRESSED_SUBSTRINGS = ("getUpdates",)

# Telegram bot tokens look like "<bot id>:<35-char secret>". httpx logs every
# request URL at INFO, and the Bot API puts the token in the path
# (/bot<token>/sendMessage), so the token would otherwise land in docker logs
# and the log files.
_BOT_TOKEN_RE = re.compile(r"\d+:[A-Za-z0-9_-]{30,}")


class _RedactingFormatter(logging.Formatter):
    # Redacts the fully formatted output, so tracebacks and every logger
    # (httpx, httpcore, telegram) are covered, not just record.msg.
    def format(self, record: logging.LogRecord) -> str:
        return _BOT_TOKEN_RE.sub("<redacted>", super().format(record))


class _HttpxFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno == logging.INFO:
            msg = record.getMessage()
            if any(s in msg for s in _SUPPRESSED_SUBSTRINGS):
                return False
        return True


def init_logging(file: Path | None, level: str) -> None:
    root = logging.getLogger()
    if root.handlers:
        return

    fmt = _RedactingFormatter("%(asctime)s %(levelname)-8s %(name)s — %(message)s")

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    if file:
        file.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(file, maxBytes=5 * 1024 * 1024, backupCount=3)
        fh.setFormatter(fmt)
        root.addHandler(fh)

    root.setLevel(level.upper())

    logging.getLogger("httpx").addFilter(_HttpxFilter())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
