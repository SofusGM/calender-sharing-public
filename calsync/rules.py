from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import holidays

from .models import Event


class Rules:
    """Afgør hvilke aftaler der er relevante for den anden."""

    def __init__(self, cfg: dict, tz: ZoneInfo):
        self.tz = tz
        self.weekday_from = time.fromisoformat(cfg.get("weekday_from", "17:00"))
        self.weekends_all_day = cfg.get("weekends_all_day", True)
        self.holidays_all_day = cfg.get("holidays_all_day", True)
        self.all_day_events = cfg.get("all_day_events", True)
        self.extra_days_off = set(cfg.get("extra_days_off", []))
        self._holidays = holidays.country_holidays(cfg.get("holidays_country", "DK"))

    def is_day_off(self, day: date) -> bool:
        if self.weekends_all_day and day.weekday() >= 5:
            return True
        if self.holidays_all_day and (
            day in self._holidays or day.strftime("%m-%d") in self.extra_days_off
        ):
            return True
        return False

    def is_relevant(self, event: Event) -> bool:
        if event.all_day:
            return self.all_day_events

        start = event.start.astimezone(self.tz)
        end = event.end.astimezone(self.tz)
        if end <= start:
            end = start + timedelta(minutes=1)

        # Gå dag for dag gennem aftalen (den kan strække sig over flere dage).
        day = start.date()
        while True:
            day_start = datetime.combine(day, time.min, self.tz)
            next_day = datetime.combine(day + timedelta(days=1), time.min, self.tz)
            if day_start >= end:
                return False
            if self.is_day_off(day):
                return True
            threshold = datetime.combine(day, self.weekday_from, self.tz)
            if min(end, next_day) > threshold:
                return True
            day += timedelta(days=1)
