"""Sikkerhed: programmet må aldrig ændre i de rigtige kalendere."""
import ast
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import icalendar
import pytest

from calsync import google_cal
from calsync.google_cal import SYNC_ID, GoogleAccount
from calsync.icloud_cal import ICloudAccount
from calsync.models import UnsafeTargetError

TZ = ZoneInfo("Europe/Copenhagen")
START, END = datetime(2026, 10, 1, tzinfo=TZ), datetime(2026, 12, 1, tzinfo=TZ)


def test_google_scopes_cannot_write_to_real_calendars():
    assert set(google_cal.SCOPES) == {
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.app.created",
    }
    # Login-scriptet skal bede om præcis de samme tilladelser.
    tree = ast.parse(Path("scripts/google_auth.py").read_text())
    script_scopes = next(
        ast.literal_eval(n.value) for n in tree.body
        if isinstance(n, ast.Assign) and n.targets[0].id == "SCOPES"
    )
    assert set(script_scopes) == set(google_cal.SCOPES)


class _Req:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeGoogle:
    def __init__(self, target_events):
        self.target_events = target_events

    def calendarList(self):
        class _L:
            def list(self, pageToken=None):
                return _Req({"items": [
                    {"id": "primary", "summary": "Mig", "accessRole": "owner"},
                    {"id": "shared", "summary": "Anna", "accessRole": "owner"},
                ]})
        return _L()

    def events(self):
        fake = self

        class _E:
            def list(self, pageToken=None, calendarId=None, **kwargs):
                assert calendarId == "shared"
                return _Req({"items": fake.target_events})
        return _E()


def ours(event_id):
    return {"id": event_id, "extendedProperties": {"private": {SYNC_ID: event_id}}}


def test_google_refuses_calendar_with_foreign_events():
    acc = GoogleAccount("all", "Anna", TZ, service=FakeGoogle([ours("a"), {"id": "real"}]))
    with pytest.raises(UnsafeTargetError, match="1 aftale"):
        acc.list_managed(START, END)


def test_google_uses_calendar_with_only_own_events():
    acc = GoogleAccount("all", "Anna", TZ, service=FakeGoogle([ours("a"), ours("b")]))
    assert [m.sync_id for m in acc.list_managed(START, END)] == ["a", "b"]


class FakeObj:
    def __init__(self, uid):
        cal = icalendar.Calendar.from_ical(
            f"BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:{uid}\nEND:VEVENT\nEND:VCALENDAR\n")
        self.icalendar_component = cal.walk("VEVENT")[0]


class FakeCal:
    url = "https://example/shared/"

    def __init__(self, uids):
        self.objs = [FakeObj(u) for u in uids]

    def get_supported_components(self):
        return ["VEVENT"]

    def get_display_name(self):
        return "Anna"

    def events(self):
        return self.objs

    def search(self, **kwargs):
        return self.objs


class FakePrincipal:
    def __init__(self, cal):
        self.cal = cal

    def calendars(self):
        return [self.cal]


def test_icloud_refuses_calendar_with_foreign_events():
    cal = FakeCal(["x@calsync", "rigtig-aftale"])
    acc = ICloudAccount("all", "Anna", TZ, principal=FakePrincipal(cal))
    with pytest.raises(UnsafeTargetError):
        acc.list_managed(START, END)


def test_icloud_uses_calendar_with_only_own_events():
    cal = FakeCal(["x@calsync", "y@calsync"])
    acc = ICloudAccount("all", "Anna", TZ, principal=FakePrincipal(cal))
    assert [m.sync_id for m in acc.list_managed(START, END)] == ["x", "y"]


def test_google_access_must_match_narrow_scopes_exactly():
    google_cal.check_granted_scopes(set(google_cal.SCOPES))
    broad = set(google_cal.SCOPES) | {"https://www.googleapis.com/auth/calendar"}
    with pytest.raises(google_cal.GoogleAccessError):
        google_cal.check_granted_scopes(broad)
    with pytest.raises(google_cal.GoogleAccessError):
        google_cal.check_granted_scopes({"https://www.googleapis.com/auth/calendar"})


def test_service_refuses_token_with_broad_access(monkeypatch):
    for name in ("GOOGLE_REFRESH_TOKEN", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
        monkeypatch.setenv(name, "x")
    monkeypatch.setattr(google_cal.Credentials, "refresh", lambda self, request: None)
    monkeypatch.setattr(google_cal, "_granted_scopes",
                        lambda token: {"https://www.googleapis.com/auth/calendar"})
    built = []
    monkeypatch.setattr(google_cal, "build", lambda *a, **k: built.append(1))
    with pytest.raises(google_cal.GoogleAccessError):
        google_cal._service()
    assert built == []


# --- Omdøbt delt kalender: egne kopier må aldrig sendes retur ---------------

def test_google_never_reads_own_copies_as_source():
    from calsync.google_cal import parse_event
    copy = {"id": "c", "summary": "Bo: Middag",
            "start": {"dateTime": "2026-10-27T18:00:00+01:00"},
            "end": {"dateTime": "2026-10-27T19:00:00+01:00"},
            "extendedProperties": {"private": {SYNC_ID: "abc"}}}
    assert parse_event(copy, "cal", TZ) is None


def test_icloud_never_reads_own_copies_as_source():
    from calsync.icloud_cal import parse_component
    copy = icalendar.Calendar.from_ical(
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:abc@calsync\nSUMMARY:Anna: Middag\n"
        "DTSTART:20261027T170000Z\nDTEND:20261027T180000Z\nEND:VEVENT\nEND:VCALENDAR\n"
    ).walk("VEVENT")[0]
    assert parse_component(copy, "cal", TZ) is None


class FakeGoogleRenamed:
    """Den delte kalender er omdøbt, så navnet i config ikke findes."""

    def __init__(self):
        self.inserted = []

    def calendarList(self):
        class _L:
            def list(self, pageToken=None):
                return _Req({"items": [
                    {"id": "primary", "summary": "Mig", "accessRole": "owner"},
                    {"id": "shared", "summary": "Gammelt navn", "accessRole": "owner"},
                ]})
        return _L()

    def calendars(self):
        fake = self

        class _C:
            def insert(self, body):
                fake.inserted.append(body)
                return _Req({"id": "new"})
        return _C()

    def events(self):
        class _E:
            def list(self, pageToken=None, calendarId=None, **kwargs):
                if calendarId == "shared":
                    return _Req({"items": [ours("a")]})
                return _Req({"items": [{"id": "rigtig", "summary": "Tandlæge"}]})
        return _E()


def test_google_reuses_renamed_shared_calendar_instead_of_creating_new():
    svc = FakeGoogleRenamed()
    acc = GoogleAccount("all", "Hvad laver Bo?", TZ, service=svc)
    assert acc.target_id() == "shared"
    assert svc.inserted == []
    assert acc._source_calendar_ids() == ["primary"]


class FakeCalNamed(FakeCal):
    def __init__(self, name, url, uids):
        super().__init__(uids)
        self.name, self.url = name, url

    def get_display_name(self):
        return self.name


class FakePrincipalMany:
    def __init__(self, cals):
        self.cals, self.made = cals, []

    def calendars(self):
        return self.cals

    def make_calendar(self, name):
        self.made.append(name)


def test_icloud_reuses_renamed_shared_calendar_instead_of_creating_new():
    real = FakeCalNamed("Arbejde", "https://example/real/", ["rigtig-aftale"])
    shared = FakeCalNamed("Hvad skal Anna", "https://example/shared/", ["x@calsync"])
    principal = FakePrincipalMany([real, shared])
    acc = ICloudAccount("all", "Hvad skal Anna?", TZ, principal=principal)
    assert acc.target() is shared
    assert principal.made == []
