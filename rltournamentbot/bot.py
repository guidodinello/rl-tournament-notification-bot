from __future__ import annotations

import asyncio
import json
import re
from datetime import date
from functools import wraps
from pathlib import Path
from typing import Any, TypedDict

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackContext,
    CommandHandler,
)
from telegram.helpers import escape_markdown

from .config import Config
from .liquipedia import fetch_upcoming_tournaments
from .logger import get_logger
from .models import Tournament

logger = get_logger(__name__)


class BotData(TypedDict):
    config: Config
    chat_store: ChatStore
    announced: AnnouncedTracker
    notify_lock: asyncio.Lock
    _application: Application


CustomContext = CallbackContext[Any, dict, dict, BotData]

_TYPE_ICONS = {
    "World Championship": "\U0001f3c6",
    "Major": "\U0001f30d",
    "Open": "\U0001f3b2",
    "Last Chance Qualifier": "\U0001f3aa",
}

_TYPE_LABELS = {
    "World Championship": "World Championship",
    "Major": "Major",
    "Open": "Opens",
    "Last Chance Qualifier": "Last Chance Qualifier",
}

MONTHS_ES = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]


def _format_date(d: date) -> str:
    return f"{d.day} de {MONTHS_ES[d.month - 1]}"


def _tournament_id(t: Tournament) -> str:
    # Excludes start_date so a Liquipedia date nudge isn't seen as a new event
    # (which would re-fire or, mid-window, drop the alert). Includes the
    # Liquipedia URL -- stable per event page -- so distinct same-name/region
    # occurrences (e.g. two Opens in a season) stay distinct; the name already
    # carries the year and mode. Falls back to name+region when no URL is set.
    raw = f"{t.name}-{t.region}-{t.liquipedia_url}".lower()
    return re.sub(r"[^a-z0-9-]+", "-", raw).strip("-")


def _build_tournament_keyboard(t: Tournament) -> InlineKeyboardMarkup:
    full_url = f"https://liquipedia.net{t.liquipedia_url}"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Ver en Liquipedia", url=full_url)],
        ]
    )


def _format_tournament_message(t: Tournament, days_left: int) -> str:
    icon = _TYPE_ICONS.get(t.event_type, "\U0001f3c6")
    mode_tag = f" [{t.mode}]" if t.mode else ""
    name = f"{icon} *{escape_markdown(t.name, version=1)}*{mode_tag}"
    date_str = _format_date(t.start_date)
    day_str = f"\U0001f4c5 *{days_left} d\u00edas*" if days_left > 0 else "\U0001f4c5 \u00a1Hoy!"

    lines = [
        name,
        "",
        f"\U0001f4c5 Comienza: {date_str} {day_str}",
        f"\U0001f30d Regi\u00f3n: {t.region}",
    ]

    return "\n".join(lines)


class ChatStore:
    def __init__(self, path: Path = Path("user_chats.json")):
        self.path = path
        self._chats: dict[str, int] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                self._chats = {str(k): v for k, v in data.get("chats", {}).items()}
            except (json.JSONDecodeError, OSError):
                self._chats = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"chats": self._chats}, indent=2))

    def set_chat(self, user_id: int, chat_id: int) -> None:
        if self._chats.get(str(user_id)) == chat_id:
            return
        self._chats[str(user_id)] = chat_id
        self._save()

    def get_chat(self, user_id: int) -> int | None:
        return self._chats.get(str(user_id))


class AnnouncedTracker:
    def __init__(self, path: Path = Path("announced.json")):
        self.path = path
        self._announced: set[str] = set()
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                self._announced = set(data.get("announced", []))
            except (json.JSONDecodeError, OSError):
                self._announced = set()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"announced": list(self._announced)}, indent=2))

    def is_announced(self, tid: str) -> bool:
        return tid in self._announced

    def mark_announced(self, tid: str) -> None:
        self._announced.add(tid)
        self._save()

    def clear(self) -> None:
        self._announced.clear()
        self._save()

    def remove(self, tid: str) -> None:
        self._announced.discard(tid)
        self._save()


def _require_auth(handler):
    @wraps(handler)
    async def wrapper(update: Update, context: CustomContext):
        user = update.effective_user
        config = context.bot_data["config"]
        if user is None or user.id not in config.allowed_user_ids:
            logger.warning("Unauthorized access attempt from user %s", user)
            if update.callback_query:
                await update.callback_query.answer("Access denied.")
            elif update.message:
                await update.message.reply_text("Access denied.")
            return
        # Remember the chat for every authorized interaction (not just /start),
        # so a user who only ever runs /next is still reachable for push alerts.
        chat = update.effective_chat
        if chat is not None:
            context.bot_data["chat_store"].set_chat(user.id, chat.id)
        return await handler(update, context)

    return wrapper


@_require_auth
async def cmd_start(update: Update, context: CustomContext) -> None:
    if update.message is None:
        return
    # The chat is registered by @_require_auth, so no need to do it here.
    await update.message.reply_text(
        "\U0001f916 \u00a1Hola! Soy el bot de notificaciones de torneos RLCS.\n\n"
        "Te avisar\u00e9 cuando se acerque un torneo.\n\n"
        "Comandos:\n"
        "/next \u2014 Pr\u00f3ximo torneo RLCS\n"
        "/schedule \u2014 Todos los pr\u00f3ximos torneos\n"
        "/refresh \u2014 Recargar datos desde Liquipedia\n"
        "/help \u2014 Este mensaje"
    )


@_require_auth
async def cmd_help(update: Update, context: CustomContext) -> None:
    await cmd_start(update, context)


@_require_auth
async def cmd_next(update: Update, context: CustomContext) -> None:
    if update.message is None:
        return

    msg = await update.message.reply_text("Buscando pr\u00f3ximo torneo...")
    tournaments = await fetch_upcoming_tournaments()
    if not tournaments:
        await msg.edit_text("No se encontraron torneos RLCS pr\u00f3ximos.")
        return

    next_t = tournaments[0]
    days = (next_t.start_date - date.today()).days
    text = _format_tournament_message(next_t, days)
    keyboard = _build_tournament_keyboard(next_t)
    await msg.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)


@_require_auth
async def cmd_schedule(update: Update, context: CustomContext) -> None:
    if update.message is None:
        return

    msg = await update.message.reply_text("Cargando calendario...")
    tournaments = await fetch_upcoming_tournaments()
    if not tournaments:
        await msg.edit_text("No se encontraron torneos RLCS pr\u00f3ximos.")
        return

    groups: dict[str, list[Tournament]] = {}
    for t in tournaments:
        groups.setdefault(t.event_type, []).append(t)

    lines: list[str] = ["\U0001f4cb *Pr\u00f3ximos torneos RLCS:*\n"]

    type_order = ["World Championship", "Major", "Open", "Last Chance Qualifier"]
    today = date.today()

    for event_type in type_order:
        group = groups.get(event_type)
        if not group:
            continue

        icon = _TYPE_ICONS.get(event_type, "\U0001f3c6")
        label = _TYPE_LABELS.get(event_type, event_type)
        lines.append(f"{icon} *{label}*")

        for t in group:
            days = (t.start_date - today).days
            date_str = _format_date(t.start_date)
            region_safe = escape_markdown(t.region, version=1)
            day_str = f"{days} d\u00edas" if days > 0 else "\u00a1Hoy!"

            if event_type in ("World Championship", "Major"):
                lines.append(f"  \u2022 {region_safe} \u2014 {day_str} ({date_str})")
            elif event_type == "Open":
                lines.append(
                    f"  \u2022 {t.mode} \u2014 {region_safe} \u2014 {day_str} ({date_str})"
                )
            else:
                lines.append(f"  \u2022 {region_safe} \u2014 {day_str} ({date_str})")

        lines.append("")

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


@_require_auth
async def cmd_refresh(update: Update, context: CustomContext) -> None:
    if update.message is None:
        return

    await update.message.reply_text("Recargando datos desde Liquipedia...")
    tournaments = await fetch_upcoming_tournaments()
    if tournaments:
        await update.message.reply_text(f"Listo. {len(tournaments)} torneo(s) encontrado(s).")
        await _check_and_notify(context.bot_data, tournaments, force_notify=False)
    else:
        await update.message.reply_text("No se encontraron torneos o hubo un error.")


async def _check_and_notify(
    bot_data: BotData,
    tournaments: list[Tournament],
    *,
    force_notify: bool = False,
) -> None:
    config = bot_data["config"]
    announced = bot_data["announced"]
    chat_store = bot_data["chat_store"]
    lock = bot_data["notify_lock"]
    app = bot_data.get("_application")
    today = date.today()

    if app is None:
        logger.warning("Application not ready yet; skipping notification check")
        return

    # Serialize against a concurrent caller (background poll vs. /refresh): both
    # share one tracker, so without this the check-then-send-then-mark window
    # (which spans an await) could let both send the same notification.
    async with lock:
        for t in tournaments:
            days = (t.start_date - today).days
            if days > config.notify_days_ahead and not force_notify:
                continue

            tid = _tournament_id(t)
            text = _format_tournament_message(t, days)
            keyboard = _build_tournament_keyboard(t)

            for uid in config.allowed_user_ids:
                # Dedup per user: a missing chat or a failed send for one user
                # must not suppress the alert for the others.
                key = f"{tid}:{uid}"
                if announced.is_announced(key) and not force_notify:
                    continue

                chat_id = chat_store.get_chat(uid)
                if chat_id is None:
                    logger.warning("No chat_id stored for user %s, skipping notification", uid)
                    continue

                try:
                    await app.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode="Markdown",
                        reply_markup=keyboard,
                    )
                    # Mark only after this user's delivery succeeds, so a missing
                    # chat or a transient failure stays retryable on the next poll.
                    announced.mark_announced(key)
                    logger.info("Notified user %s about %s (starts in %d days)", uid, t.name, days)
                except Exception:
                    logger.exception("Failed to send notification for %s to user %s", t.name, uid)


async def _poll_task(app: Application, config: Config) -> None:
    logger.info(
        "Poll task started (interval=%d min, notify_days_ahead=%d)",
        config.poll_interval_minutes,
        config.notify_days_ahead,
    )

    while True:
        try:
            logger.info("Polling Liquipedia for new tournaments...")
            tournaments = await fetch_upcoming_tournaments()
            if tournaments:
                await _check_and_notify(app.bot_data, tournaments)
        except asyncio.CancelledError:
            logger.info("Poll task cancelled")
            break
        except Exception:
            logger.exception("Error in poll task")

        # Sleep outside the work try/except so an error never skips the wait
        # and busy-loops on Liquipedia.
        try:
            await asyncio.sleep(config.poll_interval_minutes * 60)
        except asyncio.CancelledError:
            logger.info("Poll task cancelled")
            break


def build_application(config: Config, app: Application) -> Application:
    app.bot_data["config"] = config
    app.bot_data["chat_store"] = ChatStore(config.state_dir / "user_chats.json")
    app.bot_data["announced"] = AnnouncedTracker(config.state_dir / "announced.json")
    app.bot_data["notify_lock"] = asyncio.Lock()
    app.bot_data["_application"] = app

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("next", cmd_next))
    app.add_handler(CommandHandler("schedule", cmd_schedule))
    app.add_handler(CommandHandler("refresh", cmd_refresh))

    return app
