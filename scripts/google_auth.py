"""Kør én gang på din egen computer for at få et Google refresh token.

    pip install google-auth-oauthlib
    python scripts/google_auth.py sti/til/client_secret.json

Åbner en browser, hvor du giver adgang til din kalender, og udskriver
de tre værdier, der skal gemmes som GitHub-secrets.
"""

import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

# Skal matche calsync/google_cal.py: læse alt, skrive kun i appens egne kalendere.
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.app.created",
]


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    path = sys.argv[1]
    flow = InstalledAppFlow.from_client_secrets_file(path, SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    client = json.load(open(path))["installed"]
    print("\nGem disse som secrets i GitHub-repoet:\n")
    print(f"GOOGLE_CLIENT_ID     = {client['client_id']}")
    print(f"GOOGLE_CLIENT_SECRET = {client['client_secret']}")
    print(f"GOOGLE_REFRESH_TOKEN = {creds.refresh_token}")


if __name__ == "__main__":
    main()
