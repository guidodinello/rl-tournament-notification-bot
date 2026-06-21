import re
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


def _parse_days_away(text: str) -> date | None:
    m = _DAYS_AWAY_RE.search(text)
    if m:
        return date.today() + timedelta(days=int(m.group(1)))
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


def _is_rlcs_event(heading_text: str) -> bool:
    text = heading_text.lower()
    if "rlcs" in text:
        return True
    return "last chance qualifier" in text


def _is_skip_panel(heading_text: str) -> bool:
    text = heading_text.lower()
    skips = ["3v3 teams", "2v2 finals", "international events"]
    return any(s in text for s in skips)


def _parse_worlds_or_major(heading: Tag, body: Tag | None, heading_text: str) -> list[Tournament]:
    name = heading_text.replace("\u2013", "-").replace("\u2014", "-").strip()
    name = " ".join(name.split())

    start_date = _parse_days_away(heading_text)
    if not start_date:
        start_date = date.today()

    region = _extract_region_from_flag(heading)

    url = RLCS_BASE
    if body:
        links = body.select("a[href]")
        for link in links:
            href = link["href"]
            if href.startswith(RLCS_BASE):
                url = href
                break

    event_type = "World Championship" if "World Championship" in name else "Major"

    return [
        Tournament(
            name=name,
            start_date=start_date,
            end_date=None,
            region=region,
            liquipedia_url=url,
            event_type=event_type,
            mode="3v3",
        )
    ]


def _parse_lcq(heading: Tag, body: Tag | None, heading_text: str) -> list[Tournament]:
    if not body:
        return []

    tournaments: list[Tournament] = []
    cols = _get_lp_cols(body)

    for col in cols:
        region_url, region_name = _extract_region_url(col)
        timer = col.select_one(".timer-object")
        start_dt: datetime | None = None
        if timer and timer.get("data-timestamp"):
            start_dt = _parse_datetime(timer["data-timestamp"])
        start_date = start_dt.date() if start_dt else date.today() + timedelta(days=1)

        tournaments.append(
            Tournament(
                name=f"RLCS 2026 Last Chance Qualifier \u2014 {region_name}",
                start_date=start_date,
                end_date=None,
                region=region_name,
                liquipedia_url=region_url,
                event_type="Last Chance Qualifier",
                mode="3v3",
                start_time=start_dt,
            )
        )

    return tournaments


def _parse_opens(body: Tag | None, heading_text: str) -> list[Tournament]:
    if not body:
        return []

    tournaments: list[Tournament] = []
    tabs_content = body.select_one(".tabs-content")
    if not tabs_content:
        return tournaments

    modes = {"content1": "2v2", "content2": "1v1"}

    for class_name, mode in modes.items():
        tab = tabs_content.select_one(f".{class_name}")
        if not tab:
            continue

        cols = _get_lp_cols(tab)
        for col in cols:
            region_url, region_name = _extract_region_url(col)
            timer = col.select_one(".timer-object")
            start_dt: datetime | None = None
            if timer and timer.get("data-timestamp"):
                start_dt = _parse_datetime(timer["data-timestamp"])
            start_date = start_dt.date() if start_dt else None

            if start_date and start_date >= date.today():
                tournaments.append(
                    Tournament(
                        name=f"RLCS 2026 {mode} Open \u2014 {region_name}",
                        start_date=start_date,
                        end_date=None,
                        region=region_name,
                        liquipedia_url=region_url,
                        event_type="Open",
                        mode=mode,
                        start_time=start_dt,
                    )
                )

    return tournaments


def _parse_panel(panel: Tag) -> list[Tournament]:
    heading = panel.select_one(".panel-box-heading")
    if not heading:
        return []

    heading_text = heading.get_text(" ", strip=True)

    if _is_skip_panel(heading_text):
        return []

    if not _is_rlcs_event(heading_text):
        return []

    body = panel.select_one(".panel-box-body, .panel-box-collapsible-content")

    if "RLCS" in heading_text and "World Championship" in heading_text:
        return _parse_worlds_or_major(heading, body, heading_text)

    if "RLCS" in heading_text and "Major" in heading_text:
        return _parse_worlds_or_major(heading, body, heading_text)

    if "Last Chance Qualifier" in heading_text:
        return _parse_lcq(heading, body, heading_text)

    if "RLCS" in heading_text and "Opens" in heading_text:
        return _parse_opens(body, heading_text)

    return []


def parse_tournaments(html: str) -> list[Tournament]:
    soup = BeautifulSoup(html, "lxml")
    tournaments: list[Tournament] = []

    root = soup.select_one("div.mw-parser-output")
    if not root:
        logger.warning("Could not find mw-parser-output div")
        return tournaments

    panels = root.find_all("div", class_="panel-box", recursive=False)

    for panel in panels:
        try:
            result = _parse_panel(panel)
            tournaments.extend(result)

            nested = panel.find_all("div", class_="panel-box", recursive=True)
            for child in nested:
                if child is panel:
                    continue
                try:
                    result = _parse_panel(child)
                    tournaments.extend(result)
                except Exception:
                    logger.exception("Error parsing nested panel")

        except Exception:
            logger.exception("Error parsing panel")

    return tournaments


_RAW_HTML_DIR = Path("data")
_RAW_HTML_VERSION = 1


def _save_raw_html(html: str) -> None:
    _RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"v{_RAW_HTML_VERSION}-{date.today()}.html"
    path = _RAW_HTML_DIR / filename
    path.write_text(html)
    logger.info("Saved raw HTML to %s", path)


async def fetch_upcoming_tournaments() -> list[Tournament]:
    logger.info("Fetching RLCS events from Liquipedia")
    headers = {"User-Agent": USER_AGENT}

    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            html = await _fetch_page_html(session, "Liquipedia:RLCS_Events")
            _save_raw_html(html)
        except Exception:
            logger.exception("Failed to fetch RLCS Events page")
            return []

        try:
            all_tournaments = await _run_parser(html)
        except Exception:
            logger.exception("Failed to parse tournament data")
            return []

        today = date.today()
        upcoming = [t for t in all_tournaments if t.start_date >= today]
        upcoming.sort(
            key=lambda t: (
                t.start_time
                or datetime(
                    t.start_date.year, t.start_date.month, t.start_date.day, 23, 59, 59, tzinfo=UTC
                )
            )
        )

        logger.info("Found %d upcoming RLCS tournaments", len(upcoming))
        return upcoming


async def _run_parser(html: str) -> list[Tournament]:
    return parse_tournaments(html)
