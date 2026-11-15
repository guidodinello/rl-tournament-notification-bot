import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import aiohttp
from bs4 import BeautifulSoup, Tag

from .logger import get_logger
from .models import Tournament

logger = get_logger(__name__)

LIQUIPEDIA_API = "https://liquipedia.net/rocketleague/api.php"
USER_AGENT = "RLTournamentBot/1.0 (https://github.com/guido/rl-tournament-bot)"
RLCS_BASE = "/rocketleague/Rocket_League_Championship_Series"

_DAYS_AWAY_RE = re.compile(r"(\d+)\s*Days?\s*Away", re.IGNORECASE)
_CHAMPION_RE = re.compile(r"\bChampions?\b", re.IGNORECASE)
_SIDE_MODE_RE = re.compile(r"\b[12]v[12]\b", re.IGNORECASE)
_MODE_RE = re.compile(r"\dv\d", re.IGNORECASE)
_RLCS_YEAR_RE = re.compile(r"\bRLCS\s+(\d{4})\b")
_RLCS_PREFIX_RE = re.compile(r"^\s*RLCS(\s+\d{4})?\s*:?\s*")
_TAB_CONTENT_RE = re.compile(r"content(\d+)$")


async def _fetch_page_html(session: aiohttp.ClientSession, page: str) -> str:
    params = {
        "action": "parse",
        "page": page,
        "prop": "text",
        "format": "json",
    }
    async with session.get(LIQUIPEDIA_API, params=params) as resp:
        resp.raise_for_status()
        data = await resp.json()
        return data["parse"]["text"]["*"]


def _parse_days_away(text: str, today: date) -> date | None:
    m = _DAYS_AWAY_RE.search(text)
    if m:
        return today + timedelta(days=int(m.group(1)))
    return None


def _parse_datetime(ts: str) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(ts), tz=UTC)
    except ValueError, OSError:
        return None


def _extract_region_from_flag(heading: Tag) -> str:
    flag_img = heading.select_one("span.flag img")
    if flag_img and flag_img.get("alt"):
        return flag_img["alt"]
    return "International"


def _extract_url_from_lp_col(col: Tag) -> str | None:
    links = col.find_all("a", href=True)
    for link in links:
        href = link["href"]
        if href.startswith("/rocketleague/") and "File:" not in href and "Category:" not in href:
            return href
    return None


def _get_lp_cols(body: Tag) -> list[Tag]:
    cols = body.select("lp-col")
    if not cols:
        cols = body.select(".lp-col")
    return cols


def _extract_region_url(col: Tag) -> tuple[str, str]:
    region_name = "International"
    region_url = ""

    for link in col.find_all("a", href=True):
        href = link["href"]
        if "Category:" in href or "File:" in href or "Special:Stream" in href:
            if link.select_one("img") and link.img.get("alt"):
                region_name = link.img["alt"]
            continue
        if href.startswith("/rocketleague/"):
            if not region_url:
                region_url = href
            text = link.get_text(strip=True)
            if text:
                region_name = text

    return region_url, region_name


def _in_timer_col(tag: Tag) -> bool:
    return any(
        col.select_one(".timer-object[data-timestamp]")
        for col in tag.find_parents(["lp-col", "div"])
        if col.name == "lp-col" or "lp-col" in col.get("class", [])
    )


def _extract_twitch_channels(scope: Tag, *, skip_timer_cols: bool = False) -> tuple[str, ...]:
    # skip_timer_cols leaves out the streams of region columns that have their
    # own start timer: those belong to that region's tournament (e.g. a
    # community cast of one regional Open), not to the event they sit under.
    channels: list[str] = []
    for link in scope.find_all("a", href=True):
        if skip_timer_cols and _in_timer_col(link):
            continue
        href = str(link["href"])
        if "Special:Stream/twitch/" not in href:
            continue
        channel = href.rsplit("Special:Stream/twitch/", 1)[-1].split("?")[0].split("#")[0]
        if channel and channel not in channels:
            channels.append(channel)
    return tuple(channels)


# Panels we know about and deliberately ignore: rosters/results sub-panels,
# the "International Events" container (its children are handled one by one),
# and non-RLCS circuits. Anything else that looks like an event but matches no
# rule is reported as unrecognized instead of being dropped silently.
_SKIP_HEADINGS = ("3v3 teams", "2v2 finals", "international events", "collegiate")


def _is_skip_panel(heading_text: str) -> bool:
    text = heading_text.lower()
    return any(s in text for s in _SKIP_HEADINGS)


def _clean_text(tag: Tag) -> str:
    # split() also collapses the non-breaking spaces Liquipedia uses in titles.
    return " ".join(tag.get_text(" ", strip=True).split())


def _heading_text(panel: Tag) -> str:
    heading = panel.select_one(".panel-box-heading")
    return _clean_text(heading) if heading else ""


def _is_top_level(panel: Tag) -> bool:
    return panel.find_parent("div", class_="panel-box") is None


def _is_under_international_events(panel: Tag) -> bool:
    return any(
        "international events" in _heading_text(ancestor).lower()
        for ancestor in panel.find_parents("div", class_="panel-box")
    )


def _rlcs_season(panel: Tag) -> tuple[bool, str | None]:
    """Whether the panel belongs to an RLCS panel tree, and that season's year."""
    in_rlcs = False
    for p in [panel, *panel.find_parents("div", class_="panel-box")]:
        text = _heading_text(p)
        m = _RLCS_YEAR_RE.search(text)
        if m:
            return True, m.group(1)
        if "RLCS" in text:
            in_rlcs = True
    return in_rlcs, None


def _own(panel: Tag, tags: list[Tag]) -> list[Tag]:
    """Keep only the tags that belong to this panel, not to a nested one."""
    return [t for t in tags if t.find_parent("div", class_="panel-box") is panel]


def _own_timer_cols(scope: Tag, panel: Tag) -> list[tuple[Tag, datetime]]:
    cols: list[tuple[Tag, datetime]] = []
    for col in _own(panel, _get_lp_cols(scope)):
        timer = col.select_one(".timer-object[data-timestamp]")
        start_dt = _parse_datetime(timer["data-timestamp"]) if timer else None
        if start_dt:
            cols.append((col, start_dt))
    return cols


def _is_finished(body: Tag) -> bool:
    # A nested "... Champions" result panel marks the event as over. 1v1/2v2
    # finals can wrap up while the main event is still live, so those don't count.
    for h in body.select(".panel-box-heading"):
        text = h.get_text(" ", strip=True)
        if _CHAMPION_RE.search(text) and not _SIDE_MODE_RE.search(text):
            return True
    return False


def _headline_event_type(heading_text: str) -> str:
    for keyword in ("World Championship", "Major"):
        if keyword in heading_text:
            return keyword
    return "Championship"


def _parse_days_away_event(
    heading: Tag, body: Tag | None, heading_text: str, event_type: str, today: date
) -> list[Tournament]:
    name = heading_text.replace("–", "-").replace("—", "-").strip()
    name = " ".join(name.split())
    # Strip the "N Days Away" suffix: it decrements daily, and _tournament_id
    # (bot.py) is built from name+region+url, so leaving it in would change
    # the id every day and re-trigger the notification throughout the window.
    name = _DAYS_AWAY_RE.sub("", name).strip(" -–—").strip()

    start_date = _parse_days_away(heading_text, today)
    if not start_date:
        # No countdown means the event is running or already over. Liquipedia
        # keeps a finished event's panel (with a "Champions" result) until the
        # next season is listed; without this check it would show up in /next
        # as starting today for weeks.
        if body and _is_finished(body):
            return []
        start_date = today

    region = _extract_region_from_flag(heading)

    url = (_extract_url_from_lp_col(body) if body else None) or RLCS_BASE
    twitch_channels = _extract_twitch_channels(body, skip_timer_cols=True) if body else ()

    return [
        Tournament(
            name=name,
            start_date=start_date,
            end_date=None,
            region=region,
            liquipedia_url=url,
            event_type=event_type,
            mode="3v3",
            twitch_channels=twitch_channels,
        )
    ]


def _tab_groups(panel: Tag, body: Tag) -> list[tuple[str | None, Tag]]:
    """Split a panel body into (tab label, scope) pairs; untabbed -> one group."""
    tabs_content = next(iter(_own(panel, body.select(".tabs-content"))), None)
    if tabs_content is None:
        return [(None, body)]

    container = tabs_content.parent
    groups: list[tuple[str | None, Tag]] = []
    for content in tabs_content.find_all("div", recursive=False):
        m = next((_TAB_CONTENT_RE.match(c) for c in content.get("class", [])), None)
        if not m:
            continue
        label_tag = container.select_one(f"ul.nav-tabs li.tab{m.group(1)}") if container else None
        label = label_tag.get_text(" ", strip=True) if label_tag else None
        groups.append((label or None, content))
    return groups


def _parse_regional_columns(
    panel: Tag, body: Tag, heading_text: str, year: str | None, today: date
) -> list[Tournament]:
    """One tournament per region column that carries a start timer.

    Covers every "regional qualifier" layout Liquipedia has used: the tabbed
    2v2/1v1 Opens, the untabbed 3v3 Opens and the Last Chance Qualifier.
    """
    if "Last Chance Qualifier" in heading_text:
        event_type = label = "Last Chance Qualifier"
    else:
        event_type = "Open" if "Open" in heading_text else "Qualifier"
        label = _RLCS_PREFIX_RE.sub("", heading_text)
        label = re.sub(r"\bOpens\b", "Open", label).strip()
    prefix = f"RLCS {year}" if year else "RLCS"

    tournaments: list[Tournament] = []
    for tab_label, scope in _tab_groups(panel, body):
        is_mode = bool(tab_label and _MODE_RE.fullmatch(tab_label))
        mode = tab_label if is_mode else "3v3"
        full_label = f"{tab_label} {label}" if tab_label else label

        for col, start_dt in _own_timer_cols(scope, panel):
            if start_dt.date() < today:
                continue
            region_url, region_name = _extract_region_url(col)
            tournaments.append(
                Tournament(
                    name=f"{prefix} {full_label} — {region_name}",
                    start_date=start_dt.date(),
                    end_date=None,
                    region=region_name,
                    liquipedia_url=region_url,
                    event_type=event_type,
                    mode=mode,
                    start_time=start_dt,
                    twitch_channels=_extract_twitch_channels(col),
                )
            )

    return tournaments


def _parse_panel(panel: Tag, today: date) -> tuple[list[Tournament], bool] | None:
    """Parse one panel by its structure rather than by its exact title.

    Returns (tournaments, recognized), or None when the panel looks like an
    event (countdown heading or upcoming timers) but no rule claims it.
    """
    heading = panel.select_one(".panel-box-heading")
    if not heading:
        return [], False

    heading_text = _clean_text(heading)
    if _is_skip_panel(heading_text):
        return [], False

    body = panel.select_one(".panel-box-body, .panel-box-collapsible-content")
    top_level = _is_top_level(panel)
    in_rlcs, year = _rlcs_season(panel)
    has_countdown = bool(_DAYS_AWAY_RE.search(heading_text))
    timer_cols = _own_timer_cols(body, panel) if body else []

    # Headline event: a top-level RLCS panel (World Championship, Major, Club
    # Championship, ...) that is not itself a grid of regional timers.
    if top_level and "RLCS" in heading_text and (has_countdown or not timer_cols):
        event_type = _headline_event_type(heading_text)
        return _parse_days_away_event(heading, body, heading_text, event_type, today), True

    if has_countdown and _is_under_international_events(panel):
        event = _parse_days_away_event(heading, body, heading_text, "International Event", today)
        return event, True

    # Regional qualifiers: any RLCS panel with a start timer per region column.
    if in_rlcs and body and timer_cols:
        return _parse_regional_columns(panel, body, heading_text, year, today), True

    upcoming_timers = any(dt.date() >= today for _, dt in timer_cols)
    if top_level and (has_countdown or upcoming_timers):
        return None

    return [], False


@dataclass(frozen=True, slots=True)
class ParseResult:
    tournaments: list[Tournament]
    # Headings of panels that look like events but that no rule could read.
    unrecognized: tuple[str, ...] = ()
    # True when the page was read but not a single panel was recognized: the
    # layout changed beyond what the parser understands.
    blind: bool = False
    # False when the page could not be fetched at all, so nothing is known
    # about its layout either way.
    fetched: bool = True


def parse_tournaments(html: str, *, today: date | None = None) -> ParseResult:
    today = today or date.today()
    soup = BeautifulSoup(html, "lxml")

    root = soup.select_one("div.mw-parser-output")
    if not root:
        logger.warning("Could not find mw-parser-output div")
        return ParseResult([], blind=True)

    tournaments: list[Tournament] = []
    unrecognized: list[str] = []
    recognized = 0

    for panel in root.find_all("div", class_="panel-box"):
        try:
            result = _parse_panel(panel, today)
        except Exception:
            logger.exception("Error parsing panel")
            continue
        if result is None:
            unrecognized.append(_DAYS_AWAY_RE.sub("", _heading_text(panel)).strip(" -"))
            continue
        found, was_recognized = result
        tournaments.extend(found)
        recognized += was_recognized

    return ParseResult(tournaments, tuple(unrecognized), blind=recognized == 0)


_RAW_HTML_DIR = Path("data")
_RAW_HTML_VERSION = 2


def _save_raw_html(html: str) -> None:
    _RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"v{_RAW_HTML_VERSION}-{date.today()}.html"
    path = _RAW_HTML_DIR / filename
    path.write_text(html)
    logger.info("Saved raw HTML to %s", path)


async def fetch_upcoming_tournaments() -> ParseResult:
    logger.info("Fetching RLCS events from Liquipedia")
    headers = {"User-Agent": USER_AGENT}

    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            html = await _fetch_page_html(session, "Liquipedia:RLCS_Events")
            _save_raw_html(html)
        except Exception:
            logger.exception("Failed to fetch RLCS Events page")
            return ParseResult([], fetched=False)

        try:
            result = parse_tournaments(html)
        except Exception:
            logger.exception("Failed to parse tournament data")
            return ParseResult([], blind=True)

        if result.unrecognized:
            logger.warning("Unrecognized Liquipedia panels: %s", ", ".join(result.unrecognized))
        if result.blind:
            logger.warning("No Liquipedia panel was recognized; the page layout may have changed")

        today = date.today()
        upcoming = [t for t in result.tournaments if t.start_date >= today]
        upcoming.sort(
            key=lambda t: (
                t.start_time
                or datetime(
                    t.start_date.year, t.start_date.month, t.start_date.day, 23, 59, 59, tzinfo=UTC
                )
            )
        )

        logger.info("Found %d upcoming RLCS tournaments", len(upcoming))
        return replace(result, tournaments=upcoming)
