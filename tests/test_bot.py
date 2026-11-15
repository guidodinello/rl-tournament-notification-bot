import asyncio
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from rltournamentbot import bot
from rltournamentbot.liquipedia import ParseResult, parse_tournaments

FIXTURES = Path(__file__).parent / "fixtures"


class _FakeBot:
    def __init__(self):
        self.sent: list[str] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append(text)


def _bot_data():
    fake = _FakeBot()
    data = {
        "config": SimpleNamespace(allowed_user_ids=[1]),
        "chat_store": SimpleNamespace(get_chat=lambda uid: 100),
        "parser_health": bot.ParserHealth(alerted_for=None),
        "_application": SimpleNamespace(bot=fake),
    }
    return data, fake


def _track(data, result):
    asyncio.run(bot._track_parser_health(data, result))


def test_healthy_parser_stays_quiet():
    data, fake = _bot_data()
    _track(data, ParseResult([]))
    assert fake.sent == []


def test_unrecognized_panel_alerts_once_then_reports_recovery():
    data, fake = _bot_data()
    broken = ParseResult([], unrecognized=("Rocket League Masters 2027",))

    _track(data, broken)
    _track(data, broken)
    assert len(fake.sent) == 1
    assert "Rocket League Masters 2027" in fake.sent[0]

    _track(data, ParseResult([]))
    assert len(fake.sent) == 2
    assert fake.sent[1].startswith("✅")


def test_a_different_problem_alerts_again():
    data, fake = _bot_data()
    _track(data, ParseResult([], unrecognized=("A",)))
    _track(data, ParseResult([], blind=True))
    assert len(fake.sent) == 2


def test_fetch_failure_is_not_a_format_change():
    data, fake = _bot_data()
    _track(data, ParseResult([], unrecognized=("A",)))
    _track(data, ParseResult([], fetched=False))
    assert len(fake.sent) == 1
    assert data["parser_health"]["alerted_for"] == ("A",)


def test_alert_is_retried_until_someone_receives_it():
    data, fake = _bot_data()
    data["chat_store"] = SimpleNamespace(get_chat=lambda uid: None)
    _track(data, ParseResult([], blind=True))
    assert fake.sent == []
    assert data["parser_health"]["alerted_for"] is None


def test_2027_tournaments_format_and_get_distinct_ids():
    html = (FIXTURES / "rlcs_events_2026-11-15.html").read_text()
    tournaments = parse_tournaments(html, today=date(2026, 11, 15)).tournaments

    ids = {bot._tournament_id(t) for t in tournaments}
    assert len(ids) == len(tournaments)

    for t in tournaments:
        text = bot._format_tournament_message(t)
        assert t.region in text
        assert t.event_type in bot._TYPE_ICONS
