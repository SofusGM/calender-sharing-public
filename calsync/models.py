from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class Event:
    """En aftale, uafhængigt af om den kommer fra Google eller iCloud.

    For heldagsbegivenheder er start/end `date` (end er eksklusiv, som i
    iCalendar). Ellers er de tidszone-bevidste `datetime`.
    """

    source_id: str
    summary: str
    start: date | datetime
    end: date | datetime
    all_day: bool
    location: str | None = None
    description: str | None = None

    @property
    def sync_id(self) -> str:
        """Stabilt id, der kobler kildeaftalen til kopien i målkalenderen."""
        return hashlib.sha1(self.source_id.encode()).hexdigest()[:32]

    @property
    def content_hash(self) -> str:
        """Ændrer sig, når noget synligt i aftalen ændrer sig."""
        parts = [
            self.summary,
            self.start.isoformat(),
            self.end.isoformat(),
            str(self.all_day),
            self.location or "",
            self.description or "",
        ]
        return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()


class UnsafeTargetError(RuntimeError):
    """Målkalenderen indeholder aftaler, som programmet ikke selv har lavet.
    Så er det måske en rigtig kalender, og der må ikke skrives i den."""

    def __init__(self, calendar_name: str, count: int):
        super().__init__(
            f"Kalenderen {calendar_name!r} indeholder {count} aftale(r), som ikke er "
            "lavet af kalenderdelingen. Der skrives ikke i den, så ingen rigtige "
            "aftaler kan blive ændret. Flyt eller slet de aftaler, eller giv den "
            "delte kalender et andet navn i config.yaml."
        )


@dataclass(frozen=True)
class ManagedEvent:
    """En kopi, som programmet selv har lagt i en målkalender."""

    sync_id: str
    content_hash: str
    ref: Any  # Udbyderens eget objekt/id, bruges til opdatering og sletning.
