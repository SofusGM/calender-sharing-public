from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import caldav
import icalendar
import recurring_ical_events

from .config import require_env
from .logs import public_logs
from .models import Event, ManagedEvent, UnsafeTargetError

log = logging.getLogger(__name__)

# caldav skriver rå aftaledata (inkl. titler) i sine advarsler, når den retter
# iCloud-data til. Det må ikke havne i loggen fra GitHub Actions. Et filter
# bruges frem for setLevel, fordi caldav selv nulstiller niveauet ved import.
logging.getLogger("caldav").addFilter(lambda record: record.levelno >= logging.ERROR)

ICLOUD_URL = "https://caldav.icloud.com"
UID_SUFFIX = "@calsync"
HASH_PROP = "X-CALSYNC-HASH"


def is_own_copy(comp) -> bool:
    """En kopi, som kalenderdelingen selv har lavet."""
    return str(comp.get("UID", "")).endswith(UID_SUFFIX)


def _to_aware(value: date | datetime, tz: ZoneInfo) -> date | datetime:
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=tz)  # "Flydende" tid = lokal tid.
    return value


def parse_component(comp, calendar_url: str, tz: ZoneInfo) -> Event | None:
    """Laver en VEVENT (evt. én forekomst af en gentagelse) om til en Event."""
    if str(comp.get("STATUS", "")).upper() == "CANCELLED":
        return None
    # Egne kopier må aldrig læses som kilde – så ville de blive sendt retur.
    if is_own_copy(comp):
        return None
    start = _to_aware(comp.decoded("DTSTART"), tz)
    all_day = not isinstance(start, datetime)
    if "DTEND" in comp:
        end = _to_aware(comp.decoded("DTEND"), tz)
    elif "DURATION" in comp:
        end = start + comp.decoded("DURATION")
    else:
        end = start + timedelta(days=1) if all_day else start

    uid = str(comp.get("UID", ""))
    instance = comp.get("RECURRENCE-ID")
    instance_key = instance.to_ical().decode() if instance else start.isoformat()
    return Event(
        source_id=f"icloud:{calendar_url}:{uid}:{instance_key}",
        summary=str(comp.get("SUMMARY", "")),
        start=start,
        end=end,
        all_day=all_day,
        location=str(comp["LOCATION"]) if comp.get("LOCATION") else None,
        description=str(comp["DESCRIPTION"]) if comp.get("DESCRIPTION") else None,
    )


def build_ical(event: Event) -> str:
    cal = icalendar.Calendar()
    cal.add("prodid", "-//calsync//DA")
    cal.add("version", "2.0")
    ev = icalendar.Event()
    ev.add("uid", event.sync_id + UID_SUFFIX)
    ev.add("dtstamp", datetime.now(timezone.utc))
    if event.all_day:
        ev.add("dtstart", event.start)
        ev.add("dtend", event.end)
    else:
        ev.add("dtstart", event.start.astimezone(timezone.utc))
        ev.add("dtend", event.end.astimezone(timezone.utc))
    ev.add("summary", event.summary)
    if event.location:
        ev.add("location", event.location)
    if event.description:
        ev.add("description", event.description)
    ev.add(HASH_PROP, event.content_hash)
    cal.add_component(ev)
    return cal.to_ical().decode()


class ICloudAccount:
    def __init__(self, source_calendars, target_calendar: str, tz: ZoneInfo,
                 principal=None, dry_run: bool = False):
        self.tz = tz
        self.dry_run = dry_run
        if principal is None:
            client = caldav.DAVClient(
                url=ICLOUD_URL,
                username=require_env("ICLOUD_USERNAME"),
                password=require_env("ICLOUD_APP_PASSWORD"),
            )
            principal = client.principal()
        self.principal = principal
        self.source_names = source_calendars
        self.target_name = target_calendar
        self._target = None

    def _calendars(self):
        cals = []
        for cal in self.principal.calendars():
            try:
                components = cal.get_supported_components()
            except Exception:
                components = ["VEVENT"]
            if "VEVENT" in components:  # Spring påmindelseslister over.
                cals.append(cal)
        return cals

    def target(self):
        """Målkalenderen. Oprettes hvis den mangler – undtagen ved dry run,
        hvor der returneres None."""
        if self._target is not None:
            return self._target
        calendars = self._calendars()
        for cal in calendars:
            if cal.get_display_name() == self.target_name:
                self._target = cal
                return cal
        # Er den delte kalender omdøbt, genkendes den på sine egne kopier.
        for cal in calendars:
            if any(is_own_copy(obj.icalendar_component) for obj in cal.events()):
                log.warning("Bruger den eksisterende delte iCloud-kalender %r, selvom den "
                            "ikke hedder %r",
                            "(skjult)" if public_logs() else cal.get_display_name(),
                            self.target_name)
                self._target = cal
                return cal
        if self.dry_run:
            log.info("iCloud-kalenderen %r findes ikke endnu (oprettes ved rigtig kørsel)",
                     self.target_name)
            return None
        log.info("Opretter iCloud-kalenderen %r", self.target_name)
        self._target = self.principal.make_calendar(name=self.target_name)
        return self._target

    # --- Kilde ---------------------------------------------------------
    def list_events(self, start: datetime, end: datetime) -> list[Event]:
        target = self.target()
        target_url = str(target.url) if target is not None else None
        events = []
        for cal in self._calendars():
            if str(cal.url) == target_url:
                continue
            if self.source_names != "all" and cal.get_display_name() not in self.source_names:
                continue
            for obj in cal.search(start=start, end=end, event=True):
                # Gentagne aftaler foldes ud lokalt – iCloud gør det ikke pålideligt.
                for comp in recurring_ical_events.of(obj.icalendar_instance).between(start, end):
                    event = parse_component(comp, str(cal.url), self.tz)
                    if event:
                        events.append(event)
        return events

    # --- Mål -----------------------------------------------------------
    def list_managed(self, start: datetime, end: datetime) -> list[ManagedEvent]:
        target = self.target()
        if target is None:
            return []
        self._check_only_ours(target)
        managed = []
        for obj in target.search(start=start, end=end, event=True):
            comp = obj.icalendar_component
            uid = str(comp.get("UID", ""))
            managed.append(
                ManagedEvent(uid[: -len(UID_SUFFIX)], str(comp.get(HASH_PROP, "")), obj)
            )
        return managed

    def _check_only_ours(self, target) -> None:
        """Sikkerhedsstop: hele målkalenderen (ikke kun tidsvinduet) må kun
        indeholde aftaler, som programmet selv har lavet."""
        foreign = sum(not is_own_copy(obj.icalendar_component) for obj in target.events())
        if foreign:
            raise UnsafeTargetError(self.target_name, foreign)

    def create(self, event: Event) -> None:
        self.target().save_event(build_ical(event))

    def update(self, managed: ManagedEvent, event: Event) -> None:
        managed.ref.data = build_ical(event)
        managed.ref.save()

    def delete(self, managed: ManagedEvent) -> None:
        managed.ref.delete()
