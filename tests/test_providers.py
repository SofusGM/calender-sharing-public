from datetime import date, datetime
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events

from calsync.google_cal import parse_event
from calsync.icloud_cal import HASH_PROP, build_ical, parse_component
from calsync.models import Event

TZ = ZoneInfo("Europe/Copenhagen")

WEEKLY = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:abc
DTSTART;TZID=Europe/Copenhagen:20261027T180000
DTEND;TZID=Europe/Copenhagen:20261027T190000
RRULE:FREQ=WEEKLY;COUNT=3
SUMMARY:Yoga
END:VEVENT
END:VCALENDAR
"""


def test_recurring_events_get_unique_ids():
    cal = icalendar.Calendar.from_ical(WEEKLY)
    comps = recurring_ical_events.of(cal).between(
        datetime(2026, 10, 1, tzinfo=TZ), datetime(2026, 12, 1, tzinfo=TZ))
    events = [parse_component(c, "cal1", TZ) for c in comps]
    assert len(events) == 3
    assert len({e.sync_id for e in events}) == 3
    assert events[0].summary == "Yoga"
    assert events[0].start == datetime(2026, 10, 27, 18, tzinfo=TZ)


def test_build_ical_roundtrip():
    e = Event("x", "Anna: Fodbold", datetime(2026, 10, 27, 18, tzinfo=TZ),
              datetime(2026, 10, 27, 20, tzinfo=TZ), all_day=False, location="Banen")
    comp = icalendar.Calendar.from_ical(build_ical(e)).walk("VEVENT")[0]
    assert str(comp["SUMMARY"]) == "Anna: Fodbold"
    assert str(comp[HASH_PROP]) == e.content_hash
    assert comp.decoded("DTSTART") == e.start

    allday = Event("y", "Anna: Ferie", date(2026, 10, 27), date(2026, 10, 28), all_day=True)
    comp = icalendar.Calendar.from_ical(build_ical(allday)).walk("VEVENT")[0]
    assert comp.decoded("DTSTART") == date(2026, 10, 27)


def test_google_parse_skips_declined_and_reads_all_day():
    declined = {"id": "1", "start": {"dateTime": "2026-10-27T18:00:00+01:00"},
                "end": {"dateTime": "2026-10-27T19:00:00+01:00"},
                "attendees": [{"self": True, "responseStatus": "declined"}]}
    assert parse_event(declined, "c", TZ) is None

    allday = {"id": "2", "summary": "Ferie", "start": {"date": "2026-10-27"},
              "end": {"date": "2026-10-30"}}
    e = parse_event(allday, "c", TZ)
    assert e.all_day and e.end == date(2026, 10, 30)


def test_caldav_warnings_with_event_data_are_silenced(caplog):
    import calsync.icloud_cal  # noqa: F401  (tilføjer filteret ved import)
    from caldav.lib.vcal import fix

    bad = ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:x\nDTSTART:20261107T140000Z\n"
           "SUMMARY:Hemmelig titel \nEND:VEVENT\nEND:VCALENDAR\n")
    with caplog.at_level("DEBUG"):
        fix(bad)
    assert "Hemmelig" not in caplog.text
