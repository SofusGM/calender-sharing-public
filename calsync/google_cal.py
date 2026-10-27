from __future__ import annotations

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .config import require_env
from .logs import public_logs
from .models import Event, ManagedEvent, UnsafeTargetError

log = logging.getLogger(__name__)

# Læse alle kalendere, men kun skrive i kalendere som appen selv har oprettet.
# Google håndhæver det selv, så rigtige kalendere kan ikke ændres, heller ikke
# ved en fejl i koden.
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.app.created",
]
TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
SYNC_ID = "calsync_id"
SYNC_HASH = "calsync_hash"
# Google-specifikke "aftaler", der ikke er rigtige aftaler.
SKIPPED_EVENT_TYPES = {"workingLocation", "focusTime"}


class GoogleAccessError(RuntimeError):
    pass


def check_granted_scopes(granted: set[str]) -> None:
    """Nægter at køre, hvis Google-koden må mere (eller mindre) end SCOPES –
    fx hvis en gammel kode med fuld kalenderadgang stadig ligger i GitHub."""
    if granted != set(SCOPES):
        raise GoogleAccessError(
            "Google-koden (GOOGLE_REFRESH_TOKEN) har ikke de forventede tilladelser. "
            f"Fik: {sorted(granted)}. Forventede: {sorted(SCOPES)}. "
            "Kør scripts/google_auth.py igen og opdatér secret'en."
        )


def _granted_scopes(access_token: str) -> set[str]:
    # POST, så nøglen ikke står i URL'en – den kommer med i fejlbeskeder og logs.
    resp = requests.post(TOKENINFO_URL, data={"access_token": access_token}, timeout=30)
    resp.raise_for_status()
    return set(resp.json().get("scope", "").split())


def _service():
    # Ingen scopes angives, så adgangsnøglen får præcis det, koden er udstedt
    # med. Det gør det muligt at opdage en kode med for bred adgang.
    creds = Credentials(
        None,
        refresh_token=require_env("GOOGLE_REFRESH_TOKEN"),
        client_id=require_env("GOOGLE_CLIENT_ID"),
        client_secret=require_env("GOOGLE_CLIENT_SECRET"),
        token_uri="https://oauth2.googleapis.com/token",
    )
    creds.refresh(Request())
    check_granted_scopes(_granted_scopes(creds.token))
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _paged(request_fn, **kwargs):
    token = None
    while True:
        resp = request_fn(pageToken=token, **kwargs).execute()
        yield from resp.get("items", [])
        token = resp.get("nextPageToken")
        if not token:
            return


def parse_time(value: dict, tz: ZoneInfo) -> tuple[date | datetime, bool]:
    if "date" in value:
        return date.fromisoformat(value["date"]), True
    dt = datetime.fromisoformat(value["dateTime"])
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(value.get("timeZone") or str(tz)))
    return dt, False


def format_time(value: date | datetime, all_day: bool, tz: ZoneInfo) -> dict:
    if all_day:
        return {"date": value.isoformat()}
    return {"dateTime": value.isoformat(), "timeZone": str(tz)}


def is_own_copy(item: dict) -> bool:
    """En kopi, som kalenderdelingen selv har lavet."""
    return SYNC_ID in item.get("extendedProperties", {}).get("private", {})


def parse_event(item: dict, calendar_id: str, tz: ZoneInfo) -> Event | None:
    if item.get("status") == "cancelled":
        return None
    # Egne kopier må aldrig læses som kilde – så ville de blive sendt retur.
    if is_own_copy(item):
        return None
    if item.get("eventType") in SKIPPED_EVENT_TYPES:
        return None
    for attendee in item.get("attendees", []):
        if attendee.get("self") and attendee.get("responseStatus") == "declined":
            return None
    start, all_day = parse_time(item["start"], tz)
    end, _ = parse_time(item["end"], tz)
    return Event(
        source_id=f"google:{calendar_id}:{item['id']}",
        summary=item.get("summary", ""),
        start=start,
        end=end,
        all_day=all_day,
        location=item.get("location"),
        description=item.get("description"),
    )


class GoogleAccount:
    def __init__(self, source_calendars, target_calendar: str, tz: ZoneInfo,
                 service=None, dry_run: bool = False):
        self.tz = tz
        self.svc = service or _service()
        self.source_names = source_calendars
        self.target_name = target_calendar
        self.dry_run = dry_run
        self._target_id: str | None = None

    def _calendars(self) -> list[dict]:
        return list(_paged(self.svc.calendarList().list))

    def target_id(self) -> str | None:
        """Id på målkalenderen. Oprettes hvis den mangler – undtagen ved dry run,
        hvor der returneres None."""
        if self._target_id:
            return self._target_id
        owned = [c for c in self._calendars() if c.get("accessRole") == "owner"]
        for cal in owned:
            if cal.get("summary") == self.target_name:
                self._target_id = cal["id"]
                return self._target_id
        # Er den delte kalender omdøbt, genkendes den på sine egne kopier.
        for cal in owned:
            first_page = self.svc.events().list(calendarId=cal["id"], maxResults=25).execute()
            if any(is_own_copy(item) for item in first_page.get("items", [])):
                log.warning("Bruger den eksisterende delte Google-kalender %r, selvom den "
                            "ikke hedder %r", "(skjult)" if public_logs() else cal.get("summary"),
                            self.target_name)
                self._target_id = cal["id"]
                return self._target_id
        if self.dry_run:
            log.info("Google-kalenderen %r findes ikke endnu (oprettes ved rigtig kørsel)",
                     self.target_name)
            return None
        log.info("Opretter Google-kalenderen %r", self.target_name)
        cal = self.svc.calendars().insert(
            body={"summary": self.target_name, "timeZone": str(self.tz)}
        ).execute()
        self._target_id = cal["id"]
        return self._target_id

    def _source_calendar_ids(self) -> list[str]:
        target = self.target_id()
        ids = []
        for cal in self._calendars():
            # Kun egne kalendere – ikke abonnementer som "Helligdage i Danmark".
            if cal["id"] == target or cal.get("accessRole") != "owner":
                continue
            if self.source_names != "all" and cal.get("summary") not in self.source_names:
                continue
            ids.append(cal["id"])
        return ids

    def _list(self, calendar_id: str, start: datetime, end: datetime):
        return _paged(
            self.svc.events().list,
            calendarId=calendar_id,
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            maxResults=2500,
        )

    # --- Kilde ---------------------------------------------------------
    def list_events(self, start: datetime, end: datetime) -> list[Event]:
        events = []
        for cal_id in self._source_calendar_ids():
            for item in self._list(cal_id, start, end):
                event = parse_event(item, cal_id, self.tz)
                if event:
                    events.append(event)
        return events

    # --- Mål -----------------------------------------------------------
    def list_managed(self, start: datetime, end: datetime) -> list[ManagedEvent]:
        target = self.target_id()
        if target is None:
            return []
        self._check_only_ours(target)
        managed = []
        for item in self._list(target, start, end):
            props = item.get("extendedProperties", {}).get("private", {})
            managed.append(ManagedEvent(props[SYNC_ID], props.get(SYNC_HASH, ""), item["id"]))
        return managed

    def _check_only_ours(self, target: str) -> None:
        """Sikkerhedsstop: hele målkalenderen (ikke kun tidsvinduet) må kun
        indeholde aftaler, som programmet selv har lavet."""
        foreign = sum(
            not is_own_copy(item)
            for item in _paged(self.svc.events().list, calendarId=target, maxResults=2500)
        )
        if foreign:
            raise UnsafeTargetError(self.target_name, foreign)

    def _body(self, event: Event) -> dict:
        body = {
            "summary": event.summary,
            "start": format_time(event.start, event.all_day, self.tz),
            "end": format_time(event.end, event.all_day, self.tz),
            # Ingen påmindelser for den andens aftaler.
            "reminders": {"useDefault": False},
            "extendedProperties": {
                "private": {SYNC_ID: event.sync_id, SYNC_HASH: event.content_hash}
            },
        }
        if event.location:
            body["location"] = event.location
        if event.description:
            body["description"] = event.description
        return body

    def create(self, event: Event) -> None:
        self.svc.events().insert(calendarId=self.target_id(), body=self._body(event)).execute()

    def update(self, managed: ManagedEvent, event: Event) -> None:
        self.svc.events().update(
            calendarId=self.target_id(), eventId=managed.ref, body=self._body(event)
        ).execute()

    def delete(self, managed: ManagedEvent) -> None:
        self.svc.events().delete(calendarId=self.target_id(), eventId=managed.ref).execute()
