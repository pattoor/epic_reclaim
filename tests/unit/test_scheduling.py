from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.domain import scheduling


def test_normalize_days_accepts_and_canonicalizes():
    assert scheduling.normalize_days("thu, tue") == ["TUE", "THU"]
    assert scheduling.normalize_days("") == []
    with pytest.raises(scheduling.ScheduleError):
        scheduling.normalize_days("NOTADAY")


def test_normalize_times_validates_and_sorts():
    assert scheduling.normalize_times("19:30,14:05") == ["14:05", "19:30"]
    assert scheduling.normalize_times("") == []
    with pytest.raises(scheduling.ScheduleError):
        scheduling.normalize_times("25:00")
    with pytest.raises(scheduling.ScheduleError):
        scheduling.normalize_times("14:60")


def test_build_slots_weekly_and_daily():
    weekly = scheduling.build_slots("THU,TUE", "14:05,19:00")
    assert len(weekly) == 4
    assert all(slot.matches(datetime(2026, 10, 22)) for slot in weekly) is False
    thursday_slots = [slot for slot in weekly if slot.matches(datetime(2026, 10, 22, 15))]
    assert len(thursday_slots) == 2

    daily = scheduling.build_slots("THU", "14:05", daily=True)
    assert len(daily) == 1
    assert daily[0].matches(datetime(2026, 10, 21, 9)) is True  # Wednesday


def test_next_occurrence_rolls_forward():
    now = datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc)  # Wednesday
    slots = scheduling.build_slots("TUE,THU", "14:05")
    upcoming = scheduling.next_occurrence(slots, now)
    assert upcoming == datetime(2026, 10, 22, 14, 5, tzinfo=timezone.utc)

    after = datetime(2026, 10, 22, 20, 0, tzinfo=timezone.utc)  # Thursday evening
    upcoming = scheduling.next_occurrence(slots, after)
    assert upcoming == datetime(2026, 10, 27, 14, 5, tzinfo=timezone.utc)  # next Tuesday


def test_slugs_label_roundtrip():
    slot = scheduling.Slot(day="THU", time=time(14, 5))
    assert slot.label == "THU:14:05"
