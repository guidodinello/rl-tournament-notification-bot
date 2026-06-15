from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class Tournament:
    name: str
    start_date: date
    end_date: date | None
    region: str
    liquipedia_url: str
    event_type: str
    mode: str | None
