"""Logs fra GitHub Actions er offentlige: ingen aftaledata, id'er eller e-mails."""
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httplib2
from googleapiclient.errors import HttpError

from calsync.logs import safe_error
from calsync.models import Event
from calsync.rules import Rules
from calsync.sync import sync_direction

TZ = ZoneInfo("Europe/Copenhagen")


class _Source:
    def list_events(self, start, end):
        return [Event("a", "Tandlæge", datetime(2026, 10, 27, 18, tzinfo=TZ),
                      datetime(2026, 10, 27, 19, tzinfo=TZ), all_day=False)]


class _Target:
    def list_managed(self, start, end):
        return []


def _dry_run_log(caplog):
    with caplog.at_level("INFO"):
        sync_direction(_Source(), _Target(), owner="Bo", rules=Rules({}, TZ),
                       copy_cfg={}, start=None, end=None, dry_run=True)
    return caplog.text


def test_dry_run_on_github_shows_only_counts(monkeypatch, caplog):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    text = _dry_run_log(caplog)
    assert "1 nye" in text
    assert "Tandlæge" not in text and "2026-10-27" not in text


def test_dry_run_locally_shows_details(monkeypatch, caplog):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    text = _dry_run_log(caplog)
    assert "Tandlæge" in text and "2026-10-27" in text


def test_google_error_hides_url_with_email():
    uri = "https://www.googleapis.com/calendar/v3/calendars/someone%40gmail.com/events"
    exc = HttpError(httplib2.Response({"status": 404}),
                    b'{"error": {"message": "Not Found"}}', uri=uri)
    text = safe_error(exc)
    assert "404" in text
    assert "gmail" not in text and "someone" not in text


def test_unknown_error_shows_only_its_type():
    assert safe_error(FileNotFoundError(2, "No such file", "/home/someone@gmail.com")) \
        == "FileNotFoundError"


def test_failing_run_on_github_prints_no_traceback(tmp_path):
    missing = tmp_path / "someone@gmail.com.yaml"
    result = subprocess.run(
        [sys.executable, "-m", "calsync", "--config", str(missing)],
        capture_output=True, text=True, cwd=Path(__file__).parent.parent,
        env={"GITHUB_ACTIONS": "true", "PATH": "/usr/bin:/bin"},
    )
    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "Kørslen fejlede: FileNotFoundError" in output
    assert "someone" not in output and "Traceback" not in output
