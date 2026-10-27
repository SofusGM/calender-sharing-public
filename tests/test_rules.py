from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from calsync.models import Event
from calsync.rules import Rules

TZ = ZoneInfo("Europe/Copenhagen")
CFG = {
    "weekday_from": "17:00",
    "weekends_all_day": True,
    "holidays_all_day": True,
    "holidays_country": "DK",
    "extra_days_off": ["12-24"],
    "all_day_events": True,
}


@pytest.fixture
def rules():
    return Rules(CFG, TZ)


def timed(start, end):
    return Event("id", "x", start.replace(tzinfo=TZ), end.replace(tzinfo=TZ), all_day=False)


# Tirsdag d. 27. oktober 2026 er en almindelig hverdag.
@pytest.mark.parametrize(
    "start,end,expected",
    [
        (datetime(2026, 10, 27, 9), datetime(2026, 10, 27, 10), False),
        (datetime(2026, 10, 27, 16), datetime(2026, 10, 27, 18), True),   # rækker ind over 17
        (datetime(2026, 10, 27, 15), datetime(2026, 10, 27, 17), False),  # slutter præcis 17
        (datetime(2026, 10, 27, 17), datetime(2026, 10, 27, 18), True),
        (datetime(2026, 10, 27, 20), datetime(2026, 10, 28, 1), True),
        (datetime(2026, 10, 31, 9), datetime(2026, 10, 31, 10), True),    # lørdag
        (datetime(2026, 11, 1, 9), datetime(2026, 11, 1, 10), True),      # søndag
        (datetime(2026, 4, 3, 9), datetime(2026, 4, 3, 10), True),        # langfredag
        (datetime(2026, 12, 24, 9), datetime(2026, 12, 24, 10), True),    # juleaften (ekstra)
        (datetime(2026, 10, 26, 9), datetime(2026, 10, 27, 10), True),    # over natten
    ],
)
def test_timed_events(rules, start, end, expected):
    assert rules.is_relevant(timed(start, end)) is expected


def test_timezone_is_respected(rules):
    # 15:30 UTC = 16:30 dansk vintertid -> slutter 17:30 dansk tid.
    utc = ZoneInfo("UTC")
    e = Event("id", "x", datetime(2026, 10, 27, 15, 30, tzinfo=utc),
              datetime(2026, 10, 27, 16, 30, tzinfo=utc), all_day=False)
    assert rules.is_relevant(e)


def test_all_day_events(rules):
    e = Event("id", "Ferie", date(2026, 10, 27), date(2026, 10, 28), all_day=True)
    assert rules.is_relevant(e)
    assert not Rules({**CFG, "all_day_events": False}, TZ).is_relevant(e)
