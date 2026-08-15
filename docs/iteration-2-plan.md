# Iteration 2 Plan: /next Improvements — Live indicator + multi-tournament display

> Status: **proposal** — not yet implemented. Tracked separately from the current
> `/next` sort-by-start_time change (see `implementation-plan.md`).

## Goal

Improve `/next` to:
1. Show "🔴 EN VIVO" for tournaments that have already started (by `start_time`)
2. Show **all** tournaments for the closest day (today or next day with events), not just `tournaments[0]`
3. Apply the "Live" indicator also in `/schedule` and push notifications

## Files to modify

- `rltournamentbot/bot.py` (all changes in this file)

## Changes

### 1. `_is_live(t: Tournament) -> bool` — new helper

```python
def _is_live(t: Tournament) -> bool:
    if t.start_time is None:
        return False
    return datetime.now(UTC) >= t.start_time
```

- Date-only events (Worlds/Majors parsed from "N Days Away", no `start_time`) → `False`
- Timed events where current UTC time ≥ `start_time` → `True`

### 2. `_format_tournament_message(t, *, live: bool = False)` — modify

- Add `live: bool = False` parameter
- When `live=True`: replace the countdown/¡Hoy! line with `🔴 EN VIVO` and keep the time line

### 3. `_format_short_tournament(t, *, live: bool = False) -> str` — new

Compact single-tournament entry for multi-tournament lists. Output format:

```
🔴 *RLCS 2026 1v1 Open — Europe* [1v1]
   🌍 Región: Europe
   🕒 20:00 (GMT-3) — 🔴 EN VIVO
```

When not live, omit the "— EN VIVO" suffix.

### 4. `_build_multi_tournament_keyboard(tournaments: list[Tournament]) -> InlineKeyboardMarkup` — new

One `InlineKeyboardButton` row per tournament:

```
[Ver Europe en Liquipedia]
[Ver South America en Liquipedia]
```

Button text: `"Ver {region} en Liquipedia"` (using tournament region name).

### 5. `cmd_next` — rewrite

```
async def cmd_next(update, context):
    tournaments = await fetch_upcoming_tournaments()
    if not tournaments:
        → "No se encontraron torneos."

    # Group by days_until (Uruguay-local days)
    groups: dict[int, list[Tournament]] = {}
    for t in tournaments:
        days = _days_until(t)
        groups.setdefault(days, []).append(t)

    min_days = min(groups.keys())
    next_group = groups[min_days]

    if len(next_group) == 1 and min_days > 0:
        # Single future tournament → existing single-item format
        text = _format_tournament_message(next_group[0], live=False)
        keyboard = _build_tournament_keyboard(next_group[0])
    else:
        # Multiple tournaments or today → grouped list
        header_date = datetime.now(UY_TZ).date() + timedelta(days=min_days)
        date_header = _format_date(header_date)

        lines = [f"📅 *Próximos torneos — {date_header}*\n"]
        for t in next_group:
            lines.append(_format_short_tournament(t, live=_is_live(t)))
            lines.append("")

        text = "\n".join(lines)
        keyboard = _build_multi_tournament_keyboard(next_group)

    → edit message with text and keyboard
```

### 6. `cmd_schedule` — add live indicator

In the per-tournament formatting inside `cmd_schedule`, after computing `day_str`:

```python
if _is_live(t):
    day_str = "🔴 EN VIVO"
```

This replaces the `¡Hoy!` or `X días` text with the live badge for currently-running tournaments.

### 7. `_check_and_notify` — pass live flag

```python
text = _format_tournament_message(t, live=_is_live(t))
```

This affects notifications (both push and `/refresh` force-notify). At notification time the event usually hasn't started yet (notified `notify_days_ahead` in advance), but on `/refresh --force` a live event would correctly show "EN VIVO".

## Edge cases handled

| Scenario | Behavior |
|---|---|
| Tournament started 1 minute ago | Shows "🔴 EN VIVO" |
| Tournament started hours ago, still same day | Shows "🔴 EN VIVO" (no end_time to check) |
| Date-only event (Worlds/Majors) | Never shows "EN VIVO" (no precise `start_time`) |
| Event today, not yet started | Shows time normally, no live badge |
| Multiple regions same day, all future | All shown in list, none live |
| Multiple regions same day, some live, some future | Live ones get badge, future ones don't |
| No events today | Shows next day's events grouped |
| One event next week | Falls back to existing single-item format |