from datetime import datetime
from zoneinfo import ZoneInfo

from calsync.models import Event, ManagedEvent
from calsync.rules import Rules
from calsync.sync import make_plan, sync_direction, to_shared

TZ = ZoneInfo("Europe/Copenhagen")


def ev(source_id, hour, summary="Middag"):
    return Event(source_id, summary, datetime(2026, 10, 27, hour, tzinfo=TZ),
                 datetime(2026, 10, 27, hour + 1, tzinfo=TZ), all_day=False,
                 location="Hjemme", description="hemmeligt")


def test_prefix_and_copy_settings():
    shared = to_shared(ev("a", 18), "Anna", {"location": True, "description": False})
    assert shared.summary == "Anna: Middag"
    assert shared.location == "Hjemme"
    assert shared.description is None
    assert to_shared(ev("a", 18, summary=" "), "Anna", {}).summary == "Anna: (uden titel)"


def test_plan_creates_updates_and_deletes():
    keep, changed, new = ev("keep", 18), ev("changed", 19), ev("new", 20)
    old_changed = ev("changed", 19, summary="Gammel titel")
    existing = [
        ManagedEvent(keep.sync_id, keep.content_hash, "r1"),
        ManagedEvent(changed.sync_id, old_changed.content_hash, "r2"),
        ManagedEvent("gone", "h", "r3"),
    ]
    plan = make_plan([keep, changed, new], existing)
    assert plan.create == [new]
    assert [(m.ref, e) for m, e in plan.update] == [("r2", changed)]
    assert [m.ref for m in plan.delete] == ["r3"]


class FakeSource:
    def __init__(self, events):
        self.events = events

    def list_events(self, start, end):
        return self.events


class FakeTarget:
    def __init__(self):
        self.store = {}

    def list_managed(self, start, end):
        return [ManagedEvent(e.sync_id, e.content_hash, e.sync_id) for e in self.store.values()]

    def create(self, event):
        self.store[event.sync_id] = event

    def update(self, managed, event):
        self.store[managed.ref] = event

    def delete(self, managed):
        del self.store[managed.ref]


def test_sync_direction_is_idempotent_and_filters():
    rules = Rules({"weekday_from": "17:00"}, TZ)
    source = FakeSource([ev("morning", 9), ev("evening", 18)])
    target = FakeTarget()
    args = dict(owner="Bo", rules=rules, copy_cfg={}, start=None, end=None)

    sync_direction(source, target, **args)
    assert [e.summary for e in target.store.values()] == ["Bo: Middag"]

    plan = sync_direction(source, target, **args)
    assert not (plan.create or plan.update or plan.delete)

    source.events = []
    sync_direction(source, target, **args)
    assert target.store == {}
