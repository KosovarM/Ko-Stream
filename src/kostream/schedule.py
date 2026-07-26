"""Weekly airing schedule from MAL broadcast (JST → local time)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, time, timezone

from kostream.models import Show
from kostream.watch_progress import filter_currently_airing

WEEKDAY_KEYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

WEEKDAY_LABELS = {
    "monday": "Monday",
    "tuesday": "Tuesday",
    "wednesday": "Wednesday",
    "thursday": "Thursday",
    "friday": "Friday",
    "saturday": "Saturday",
    "sunday": "Sunday",
}

# MAL broadcast times are Japan Standard Time (no DST).
_JST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class ScheduleEntry:
    show_id: str
    title: str
    poster_url: str | None
    time_local: str
    time_jst: str
    weekday_local: str
    mal_id: int | None


@dataclass(frozen=True)
class ScheduleDay:
    key: str
    label: str
    entries: list[ScheduleEntry]


def jst_broadcast_to_local(
    day: str,
    start_time: str,
    *,
    reference: datetime | None = None,
) -> tuple[str, str] | None:
    """Map MAL JST day+HH:MM → (local_weekday_key, local HH:MM) using system timezone."""
    day_key = (day or "").strip().lower()
    if day_key not in WEEKDAY_LABELS:
        return None
    parts = (start_time or "").strip().split(":")
    if len(parts) < 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    now_jst = (reference or datetime.now(tz=_JST)).astimezone(_JST)
    target_wd = WEEKDAY_KEYS.index(day_key)
    days_ahead = (target_wd - now_jst.weekday()) % 7
    dt_jst = datetime.combine(
        now_jst.date() + timedelta(days=days_ahead),
        time(hour, minute),
        tzinfo=_JST,
    )
    dt_local = dt_jst.astimezone()  # OS local timezone
    return WEEKDAY_KEYS[dt_local.weekday()], dt_local.strftime("%H:%M")


def build_weekly_schedule(shows: list[Show]) -> tuple[list[ScheduleDay], list[ScheduleEntry]]:
    """Seven weekday rows (local time) + entries with unknown broadcast."""
    buckets: dict[str, list[ScheduleEntry]] = {k: [] for k in WEEKDAY_KEYS}
    unknown: list[ScheduleEntry] = []

    for show in filter_currently_airing(shows):
        day = show.broadcast_day
        btime = show.broadcast_time
        if not day or not btime:
            unknown.append(
                ScheduleEntry(
                    show_id=show.id,
                    title=show.title,
                    poster_url=show.poster_url or show.poster,
                    time_local="—",
                    time_jst="—",
                    weekday_local="unknown",
                    mal_id=show.mal_id,
                )
            )
            continue
        converted = jst_broadcast_to_local(day, btime)
        if not converted:
            unknown.append(
                ScheduleEntry(
                    show_id=show.id,
                    title=show.title,
                    poster_url=show.poster_url or show.poster,
                    time_local=btime,
                    time_jst=f"{btime} JST",
                    weekday_local="unknown",
                    mal_id=show.mal_id,
                )
            )
            continue
        local_day, local_time = converted
        buckets[local_day].append(
            ScheduleEntry(
                show_id=show.id,
                title=show.title,
                poster_url=show.poster_url or show.poster,
                time_local=local_time,
                time_jst=f"{btime} JST",
                weekday_local=local_day,
                mal_id=show.mal_id,
            )
        )

    days: list[ScheduleDay] = []
    for key in WEEKDAY_KEYS:
        entries = sorted(buckets[key], key=lambda e: (e.time_local, e.title.casefold()))
        days.append(ScheduleDay(key=key, label=WEEKDAY_LABELS[key], entries=entries))

    unknown.sort(key=lambda e: e.title.casefold())
    return days, unknown
