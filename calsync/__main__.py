from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .config import MissingCredentials, load_config
from .logs import public_logs, safe_error
from .rules import Rules
from .sync import sync_direction

log = logging.getLogger("calsync")


class NoTarget:
    """Bruges ved dry run, når den andens konto mangler logins: viser hvad der
    ville blive delt, uden at kunne sammenligne med en målkalender."""

    def list_managed(self, start, end):
        return []


def connect(person: dict, tz: ZoneInfo, dry_run: bool):
    """Logger ind på personens konto. Mangler kontoens secrets, er den bare ikke
    sat op endnu: så springes den over i stedet for at fejle hver halve time."""
    try:
        return make_account(person, tz, dry_run)
    except MissingCredentials as e:
        log.warning("%s-kontoen springes over, fordi den ikke er sat op: %s",
                    person["provider"], e.args[0])
        return None


def make_account(person: dict, tz: ZoneInfo, dry_run: bool):
    provider = person["provider"]
    args = (person.get("source_calendars", "all"), person["target_calendar"], tz)
    if provider == "google":
        from .google_cal import GoogleAccount
        return GoogleAccount(*args, dry_run=dry_run)
    if provider == "icloud":
        from .icloud_cal import ICloudAccount
        return ICloudAccount(*args, dry_run=dry_run)
    raise ValueError(f"Ukendt udbyder: {provider}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Del relevante aftaler mellem to kalendere.")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Vis ændringer uden at skrive.")
    args = parser.parse_args()
    # Kun programmets egne beskeder på INFO; biblioteker kun ved advarsler.
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    log.setLevel(logging.INFO)

    cfg = load_config(args.config)
    tz = ZoneInfo(cfg.get("timezone", "Europe/Copenhagen"))
    rules = Rules(cfg.get("rules", {}), tz)
    copy_cfg = cfg.get("copy", {})

    window = cfg.get("sync_window", {})
    today = datetime.combine(datetime.now(tz).date(), time.min, tz)
    start = today - timedelta(days=window.get("days_back", 7))
    end = today + timedelta(days=window.get("days_ahead", 90))

    people = cfg["people"]
    if len(people) != 2:
        raise ValueError("config.yaml skal have præcis to personer under 'people'.")
    accounts = [connect(p, tz, args.dry_run) for p in people]

    for i, owner in enumerate(people):
        source, target = accounts[i], accounts[1 - i]
        if source is None:
            continue
        if target is None:
            if not args.dry_run:
                continue
            target = NoTarget()
        sync_direction(
            source=source,
            target=target,
            owner=owner["name"],
            rules=rules,
            copy_cfg=copy_cfg,
            start=start,
            end=end,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        if not public_logs():
            raise
        # Ingen traceback på GitHub: den kan indeholde URL'er, id'er og e-mails.
        log.error("Kørslen fejlede: %s (kør lokalt for detaljer)", safe_error(exc))
        sys.exit(1)
