"""Simplified cron-like scheduling helpers.

Pure functions shared by config validation, the scheduler and the settings
service. Slots are expressed as day-of-week + HH:MM pairs (default: THU 14:05;
daily preset for promotional seasons). No external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

DAY_ORDER = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
DAY_INDEX = {name: index for index, name in enumerate(DAY_ORDER)}
ALL_DAYS = DAY_ORDER  # convenience: every day of the week


class ScheduleError(ValueError):
    pass


def normalize_days(value: str) -> list[str]:
    """Parse a comma/space separated day list into canonical uppercase names."""
    days: list[str] = []
    for token in (value or "").replace(",", " ").split():
        day = token.strip().upper()[:3]
        if day not in DAY_INDEX:
            raise ScheduleError(f"invalid scheduler day: {token!r} (use MON..SUN)")
        if day not in days:
            days.append(day)
    return sorted(days, key=lambda name: DAY_INDEX[name])


def normalize_times(value: str) -> list[str]:
    """Parse a comma/space separated list of HH:MM times, validated."""
    times: list[str] = []
    for token in (value or "").replace(",", " ").split():
        try:
            parsed = time.fromisoformat(token)
        except ValueError as exc:
            raise ScheduleError(f"invalid scheduler time: {token!r} (use HH:MM)") from exc
        text = parsed.strftime("%H:%M")
        if text not in times:
            times.append(text)
    return sorted(times)


def is_valid_schedule(days: str, times: str) -> bool:
    try:
        normalize_days(days)
        normalize_times(times)
    except ScheduleError:
        return False
    return True


@dataclass(frozen=True)
class Slot:
    """One scheduled window: a specific weekday ("*": every day) at HH:MM."""

    day: str  # canonical name or "*"
    time: time

    @property
    def label(self) -> str:
        return f"{self.day}:{self.time.strftime('%H:%M')}"

    def matches(self, moment: datetime) -> bool:
        return self.day == "*" or DAY_INDEX.get(self.day) == moment.weekday()


def build_slots(days: str, times: str, daily: bool = False) -> list[Slot]:
    """Build slots from configured settings. daily=True wins over days list."""
    normalized_times = normalize_times(times)
    if not normalized_times:
        return []
    if daily:
        day_names: list[str] = ["*"]
    else:
        normalized_days = normalize_days(days)
        if not normalized_days:
            return []
        day_names = normalized_days
    slots: list[Slot] = []
    for day in day_names:
        for item in normalized_times:
            hour, minute = map(int, item.split(":"))
            slots.append(Slot(day=day, time=time(hour, minute)))
    return slots


def today_slots(slots: list[Slot], moment: datetime) -> list[Slot]:
    return [slot for slot in slots if slot.matches(moment)]


def next_occurrence(slots: list[Slot], now: datetime) -> datetime | None:
    """Next datetime strictly after *now* for the given slot set."""
    best: datetime | None = None
    for slot in slots:
        candidate = now.replace(
            hour=slot.time.hour, minute=slot.time.minute, second=0, microsecond=0
        )
        # Roll forward day by day until the candidate matches the slot and is
        # strictly in the future (bounded: weekly slots resolve within 7 days).
        for _ in range(8):
            if candidate > now and slot.matches(candidate):
                break
            candidate = candidate + timedelta(days=1)
        else:  # pragma: no cover - defensive
            continue
        if best is None or candidate < best:
            best = candidate
    return best
