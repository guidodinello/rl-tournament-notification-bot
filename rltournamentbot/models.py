from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class Tournament:
    name: str
    start_date: date
    end_date: date | None
    region: str
    liquipedia_url: str
    event_type: str
    mode: str | None
    # Precise start instant (timezone-aware, UTC) when Liquipedia exposes a
    # timer timestamp. None for events whose start we only know as a date
    # (e.g. World Championship / Major parsed from "N Days Away").
    start_time: datetime | None = None
    # Official Twitch channel logins linked from the Liquipedia panel, if any.
    twitch_channels: tuple[str, ...] = ()
    # Active Twitch Drops campaign name for this tournament, if one is
    # currently running on one of twitch_channels. None means "unknown or
    # no active campaign" -- coverage is intentionally partial (see
    # enrich_with_drops), so this is never treated as a confirmed negative.
    drops_campaign: str | None = None
