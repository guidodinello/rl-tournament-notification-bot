from datetime import UTC, date, datetime
from pathlib import Path

from rltournamentbot.liquipedia import parse_tournaments

FIXTURES = Path(__file__).parent / "fixtures"
RLCS = "/rocketleague/Rocket_League_Championship_Series"


def _parse(name: str, today: date):
    return parse_tournaments((FIXTURES / name).read_text(), today=today)


def _page(*panels: str) -> str:
    return f'<div class="mw-parser-output">{"".join(panels)}</div>'


def _panel(heading: str, body: str = "") -> str:
    return (
        '<div class="panel-box">'
        f'<div class="panel-box-heading">{heading}</div>'
        f'<div class="panel-box-body">{body}</div>'
        "</div>"
    )


def _region_col(region: str, when: datetime | None) -> str:
    timer = (
        f'<span class="timer-object" data-timestamp="{int(when.timestamp())}"></span>'
        if when
        else ""
    )
    return f'<div class="lp-col"><a href="/rocketleague/X/{region}">{region}</a>{timer}</div>'


TODAY = date(2026, 11, 15)
SOON = datetime(2026, 11, 20, 18, 0, tzinfo=UTC)


class TestClubChampionship2027:
    """The layout that went unparsed: RLCS 2027 "Club Championship - Kick-Off"."""

    result = _parse("rlcs_events_2026-11-15.html", TODAY)

    def test_nothing_is_left_unread(self):
        assert self.result.unrecognized == ()
        assert not self.result.blind

    def test_headline_event(self):
        (event,) = (t for t in self.result.tournaments if t.event_type == "Championship")
        assert event.name == "RLCS 2027: Club Championship - Kick-Off"
        assert event.start_date == date(2026, 12, 9)  # "24 Days Away"
        assert event.region == "England"
        assert event.liquipedia_url == f"{RLCS}/Club_Championship/2027/Kick-Off"
        assert event.start_time is None
        # The regional Opens' streams belong to the Opens, not to the headline.
        assert event.twitch_channels == ()

    def test_regional_opens(self):
        opens = {t.region: t for t in self.result.tournaments if t.event_type == "Open"}
        # Middle East & North Africa has no start timer yet, so it is left out.
        assert set(opens) == {"North America", "Europe", "South America"}

        na = opens["North America"]
        assert na.name == "RLCS 2027 Club Championship - Kick-Off Open — North America"
        assert na.mode == "3v3"
        assert na.start_time == datetime(2026, 11, 15, 18, 0, tzinfo=UTC)
        assert na.liquipedia_url == f"{RLCS}/Club_Championship/2027/Kick-Off/North_America"
        assert na.twitch_channels == ("Rocket_League",)

        assert opens["Europe"].start_time == datetime(2026, 11, 15, 17, 0, tzinfo=UTC)
        assert opens["South America"].start_time == datetime(2026, 11, 15, 19, 0, tzinfo=UTC)
        assert opens["South America"].twitch_channels == ("dudsmelow",)

    def test_only_these_events(self):
        assert len(self.result.tournaments) == 4


class TestWorlds2026:
    """Regression: the 2026 layout must parse exactly as it did before."""

    result = _parse("rlcs_events_2026-06-14.html", date(2026, 6, 14))

    def test_nothing_is_left_unread(self):
        assert self.result.unrecognized == ()
        assert not self.result.blind

    def test_events(self):
        got = [
            (t.name, t.start_date.isoformat(), t.event_type, t.mode)
            for t in self.result.tournaments
        ]
        lcq, open_ = "Last Chance Qualifier", "Open"
        assert got == [
            ("RLCS 2026: World Championship", "2026-09-08", "World Championship", "3v3"),
            (f"RLCS 2026 {lcq} — North America", "2026-07-03", lcq, "3v3"),
            (f"RLCS 2026 {lcq} — Europe", "2026-07-03", lcq, "3v3"),
            (f"RLCS 2026 {lcq} — South America", "2026-07-03", lcq, "3v3"),
            (f"RLCS 2026 {lcq} — Middle East & North Africa", "2026-07-02", lcq, "3v3"),
            ("RLCS 2026 1v1 Open — North America", "2026-06-21", open_, "1v1"),
            ("RLCS 2026 1v1 Open — Europe", "2026-06-19", open_, "1v1"),
            ("RLCS 2026 1v1 Open — Oceania", "2026-06-21", open_, "1v1"),
            ("RLCS 2026 1v1 Open — South America", "2026-06-19", open_, "1v1"),
            ("RLCS 2026 1v1 Open — Middle East & North Africa", "2026-06-20", open_, "1v1"),
            ("RLCS 2026 1v1 Open — Asia-Pacific", "2026-06-19", open_, "1v1"),
            ("RLCS 2026 1v1 Open — Sub-Saharan Africa", "2026-06-21", open_, "1v1"),
            ("Esports World Cup 2026", "2026-08-11", "International Event", "3v3"),
            ("Esports Nations Cup 2026", "2026-11-02", "International Event", "3v3"),
        ]

    def test_details(self):
        by_name = {t.name: t for t in self.result.tournaments}
        worlds = by_name["RLCS 2026: World Championship"]
        assert worlds.region == "United States"
        assert worlds.liquipedia_url == f"{RLCS}/2026"
        assert worlds.twitch_channels == ("Rocket_League",)

        oce = by_name["RLCS 2026 1v1 Open — Oceania"]
        assert oce.start_time == datetime(2026, 6, 21, 7, 0, tzinfo=UTC)
        assert oce.liquipedia_url == f"{RLCS}/2026/1v1/Oceania"
        assert oce.twitch_channels == ("RocketLeagueOCE", "CJCJ")

    def test_past_opens_are_dropped(self):
        # The 2v2 Opens were already played on the snapshot date.
        assert not [t for t in self.result.tournaments if t.mode == "2v2"]


class TestFutureLayouts:
    """Panels are read by structure, so renamed events keep working."""

    def test_renamed_headline_event(self):
        result = parse_tournaments(
            _page(_panel("RLCS 2028: Grand Prix - 10 Days Away")), today=TODAY
        )
        (event,) = result.tournaments
        assert event.name == "RLCS 2028: Grand Prix"
        assert event.event_type == "Championship"
        assert event.start_date == date(2026, 11, 25)

    def test_renamed_regional_panel(self):
        cols = _region_col("Europe", SOON) + _region_col("Oceania", None)
        html = _page(_panel("RLCS 2028: Grand Prix", _panel("Grand Prix - Play-Ins", cols)))
        result = parse_tournaments(html, today=TODAY)
        (play_in,) = (t for t in result.tournaments if t.event_type == "Qualifier")
        assert play_in.name == "RLCS 2028 Grand Prix - Play-Ins — Europe"
        assert play_in.start_time == SOON
        assert result.unrecognized == ()

    def test_finished_headline_event_is_dropped(self):
        html = _page(
            _panel("RLCS 2027: Club Championship - Kick-Off", _panel("Kick-Off Champions"))
        )
        assert parse_tournaments(html, today=TODAY).tournaments == []

    def test_side_mode_champions_do_not_finish_the_event(self):
        html = _page(_panel("RLCS 2027: World Championship", _panel("2v2 Champions")))
        (event,) = parse_tournaments(html, today=TODAY).tournaments
        assert event.start_date == TODAY


class TestBlindSpots:
    def test_unknown_countdown_panel_is_reported(self):
        html = _page(
            _panel("RLCS 2027: Major - 5 Days Away"),
            _panel("Rocket League Masters 2027 - 12 Days Away"),
        )
        result = parse_tournaments(html, today=TODAY)
        assert [t.name for t in result.tournaments] == ["RLCS 2027: Major"]
        assert result.unrecognized == ("Rocket League Masters 2027",)
        assert not result.blind

    def test_unknown_panel_with_upcoming_timers_is_reported(self):
        html = _page(_panel("Rocket League Masters", _region_col("Europe", SOON)))
        assert parse_tournaments(html, today=TODAY).unrecognized == ("Rocket League Masters",)

    def test_ignored_and_stale_panels_are_not_reported(self):
        past = datetime(2026, 10, 24, 18, 0, tzinfo=UTC)
        html = _page(
            _panel("RLCS 2027: Major - 5 Days Away"),
            _panel("Collegiate Rocket League Spring 2027", _region_col("Europe", SOON)),
            _panel("Some Old Cup", _region_col("Europe", past)),
        )
        assert parse_tournaments(html, today=TODAY).unrecognized == ()

    def test_page_with_no_recognized_panel_is_blind(self):
        assert parse_tournaments(_page(_panel("Something Else")), today=TODAY).blind
        assert parse_tournaments("<div>unexpected</div>", today=TODAY).blind
