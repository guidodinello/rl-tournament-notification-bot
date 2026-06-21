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
