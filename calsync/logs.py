"""Hvad der må stå i loggen. Logs fra GitHub Actions er offentlige, når repoet
er offentligt, så der må ikke komme titler, tidspunkter, kalender-id'er,
e-mailadresser eller webadresser med."""

from __future__ import annotations

import os


def public_logs() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def safe_error(exc: BaseException) -> str:
    """En fejlbesked uden personlige oplysninger."""
    from google.auth.exceptions import RefreshError
    from googleapiclient.errors import HttpError

    from .config import MissingCredentials
    from .google_cal import GoogleAccessError
    from .models import UnsafeTargetError

    # Vores egne fejl indeholder kun navne fra secrets (som GitHub skjuler).
    if isinstance(exc, (UnsafeTargetError, GoogleAccessError, MissingCredentials)):
        return str(exc.args[0])
    if isinstance(exc, HttpError):
        # Ikke str(exc): den indeholder URL'en med kalender-id/e-mail.
        return f"Google svarede {exc.status_code}: {exc.reason}"
    if isinstance(exc, RefreshError):
        return f"Google-login fejlede: {exc.args[0] if exc.args else ''}".strip()
    if type(exc).__module__.startswith("caldav"):
        return f"iCloud-fejl ({type(exc).__name__})"
    return type(exc).__name__
