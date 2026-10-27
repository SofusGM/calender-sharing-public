from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from calsync.__main__ import connect
from calsync.config import MissingCredentials, require_env
from calsync.google_cal import GoogleAccount

TZ = ZoneInfo("Europe/Copenhagen")
ICLOUD = {"provider": "icloud", "target_calendar": "Anna"}


class _Req:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeGoogle:
    """Minimal udgave af Google Calendar-klienten med én egen kalender."""

    def __init__(self):
        self.inserted = []

    def calendarList(self):
        class _L:
            def list(self, pageToken=None):
                return _Req({"items": [{"id": "primary", "summary": "Mig", "accessRole": "owner"}]})
        return _L()

    def calendars(self):
        svc = self

        class _C:
            def insert(self, body):
                svc.inserted.append(body)
                return _Req({"id": "new"})
        return _C()

    def events(self):
        class _E:
            def list(self, pageToken=None, **kwargs):
                return _Req({"items": [{
                    "id": "e1", "summary": "Fodbold",
                    "start": {"dateTime": "2026-10-27T18:00:00+01:00"},
                    "end": {"dateTime": "2026-10-27T19:00:00+01:00"},
                }]})
        return _E()


def test_empty_secret_counts_as_missing():
    with pytest.raises(MissingCredentials):
        require_env("X", {"X": ""})
    assert require_env("X", {"X": "v"}) == "v"


def test_account_without_credentials_is_skipped(monkeypatch):
    monkeypatch.setenv("ICLOUD_USERNAME", "")
    monkeypatch.delenv("ICLOUD_APP_PASSWORD", raising=False)
    assert connect(ICLOUD, TZ, dry_run=True) is None
    assert connect(ICLOUD, TZ, dry_run=False) is None


def test_google_dry_run_never_creates_target_calendar():
    svc = FakeGoogle()
    acc = GoogleAccount("all", "Anna", TZ, service=svc, dry_run=True)
    start, end = datetime(2026, 10, 1, tzinfo=TZ), datetime(2026, 11, 1, tzinfo=TZ)
    events = acc.list_events(start, end)
    assert [e.summary for e in events] == ["Fodbold"]
    assert acc.list_managed(start, end) == []
    assert svc.inserted == []


def test_google_real_run_creates_missing_target_calendar():
    svc = FakeGoogle()
    acc = GoogleAccount("all", "Anna", TZ, service=svc)
    assert acc.target_id() == "new"
    assert svc.inserted[0]["summary"] == "Anna"
