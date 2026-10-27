from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from .logs import public_logs
from .models import Event, ManagedEvent
from .rules import Rules

log = logging.getLogger(__name__)


class Source(Protocol):
    def list_events(self, start: datetime, end: datetime) -> list[Event]: ...


class Target(Protocol):
    def list_managed(self, start: datetime, end: datetime) -> list[ManagedEvent]: ...
    def create(self, event: Event) -> None: ...
    def update(self, managed: ManagedEvent, event: Event) -> None: ...
    def delete(self, managed: ManagedEvent) -> None: ...


@dataclass
class Plan:
    create: list[Event] = field(default_factory=list)
    update: list[tuple[ManagedEvent, Event]] = field(default_factory=list)
    delete: list[ManagedEvent] = field(default_factory=list)


def to_shared(event: Event, owner: str, copy_cfg: dict) -> Event:
    """Laver den udgave af aftalen, som den anden får at se."""
    title = event.summary.strip() or "(uden titel)"
    return dataclasses.replace(
        event,
        summary=f"{owner}: {title}",
        location=event.location if copy_cfg.get("location", True) else None,
        description=event.description if copy_cfg.get("description", False) else None,
    )


def make_plan(wanted: list[Event], existing: list[ManagedEvent]) -> Plan:
    plan = Plan()
    existing_by_id = {m.sync_id: m for m in existing}
    wanted_by_id = {e.sync_id: e for e in wanted}

    for sync_id, event in wanted_by_id.items():
        managed = existing_by_id.get(sync_id)
        if managed is None:
            plan.create.append(event)
        elif managed.content_hash != event.content_hash:
            plan.update.append((managed, event))

    for sync_id, managed in existing_by_id.items():
        if sync_id not in wanted_by_id:
            plan.delete.append(managed)
    return plan


def sync_direction(
    source: Source,
    target: Target,
    owner: str,
    rules: Rules,
    copy_cfg: dict,
    start: datetime,
    end: datetime,
    dry_run: bool = False,
) -> Plan:
    events = source.list_events(start, end)
    wanted = [to_shared(e, owner, copy_cfg) for e in events if rules.is_relevant(e)]
    existing = target.list_managed(start, end)
    plan = make_plan(wanted, existing)

    log.info(
        "%s: %d aftaler fundet, %d relevante -> %d nye, %d ændrede, %d slettede",
        owner, len(events), len(wanted),
        len(plan.create), len(plan.update), len(plan.delete),
    )
    if dry_run:
        # Detaljer kun lokalt – på GitHub ville de vise jeres aftaler offentligt.
        if not public_logs():
            for e in plan.create:
                log.info("  [ny] %s  %s", e.start, e.summary)
            for _, e in plan.update:
                log.info("  [ændret] %s  %s", e.start, e.summary)
            for m in plan.delete:
                log.info("  [slettet] %s", m.sync_id)
        return plan

    for e in plan.create:
        target.create(e)
    for m, e in plan.update:
        target.update(m, e)
    for m in plan.delete:
        target.delete(m)
    return plan
