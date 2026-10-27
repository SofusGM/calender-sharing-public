# Calendar sharing: Google ⇄ iCloud

Automatically shares the events that matter to the other person between one person's Google Calendar and another person's iCloud calendars.

```
Google person's calendars ──► [rules] ──► shared calendar in the iCloud account
iCloud person's calendars ──► [rules] ──► shared calendar in the Google account
```

- Each copied event gets the owner's name and a colon in front, e.g. `Anna: Dinner with Mia`.
- The shared calendars are **read-only in practice**: changes made in them are overwritten on the next run.
- Copies have no reminders and never send invitations.
- It runs every 30 minutes on GitHub Actions.

## Privacy

The repository can be public:

- **Names, logins and passwords** live only in GitHub secrets, never in the code. `config.yaml` reads the names through `${GOOGLE_PERSON_NAME}` and `${ICLOUD_PERSON_NAME}`.
- **GitHub Actions logs** (visible to everyone in a public repo) only show counts: no event titles, no times, no calendar IDs. Errors are reduced to a short, safe message without URLs or tracebacks. GitHub also masks every secret value in the logs.
- Running locally shows full details, so you can see exactly what would be shared.
- The rules in `config.yaml` (e.g. 17:00) are public but contain nothing personal.

## Safety: your real calendars are never changed

The program reads your calendars but only writes to the two shared calendars it creates itself. This is enforced in three layers:

1. **Google refuses it.** The Google access only allows *reading* calendars and *writing to calendars the app created itself*. Even with a bug in the code, your real Google calendars cannot be changed.
2. **Safety stop.** Before writing to a shared calendar, the whole calendar is checked. If it contains a single event the program didn't create, the run stops with an error and touches nothing. A real calendar that happens to have the same name can never be used.
3. **Only its own events are changed.** The program only updates and deletes events it has marked as its own, and it never reads its own copies as a source.

iCloud cannot limit an app-specific password, so on the iCloud side layers 2 and 3 are what protect you.

In addition:

- **Google access check.** On every run the program asks Google what the token is allowed to do. If it is allowed more than the above, the program refuses to run.
- **Locked dependencies.** All packages are pinned to exact versions with hashes (`requirements.txt`), and GitHub actions are pinned to exact commits.
- **Least privilege.** The workflows can only read the repository, not write to it.
- **Environment `kalender`.** The sync job runs in the `kalender` environment, limited to `main`. If the 7 secrets are stored as *environment secrets* there instead of *repository secrets*, only code on `main` can use them.

## Rules

The rules live in [`config.yaml`](config.yaml) and apply in both directions:

| When | What is shared |
|---|---|
| Weekdays | Events that extend past 17:00 (16–18 is shared, 15–17 is not) |
| Weekends | All day |
| Public holidays (+ Constitution Day, Christmas Eve, New Year's Eve) | All day |
| All-day events | Always |

Title and location are copied, notes are not. This can be changed under `copy:`.

The shared calendars are called "Hvad laver …?" ("What is … doing?") followed by the other person's name. The names can be changed under `target_calendar` in `config.yaml`. If a shared calendar is renamed, the program recognises it by its own copies and keeps using it.

## Setup

### 1. iCloud: app-specific password

1. Go to [account.apple.com](https://account.apple.com) → *Sign-In and Security* → *App-Specific Passwords*.
2. Create a new one, e.g. named "Calendar sharing", and keep the password.

### 2. Google access

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a new project.
2. *APIs & Services → Library*: enable the **Google Calendar API**.
3. *Google Auth Platform → Branding*: fill in the app name, support email and developer contact email. Leave the logo empty, since uploading one requires Google verification.
4. *Audience*: choose **External** and press **Publish app** so the app is *In production*. Otherwise the access expires after 7 days. Google warns that the app is unverified when you sign in; that is fine because it is your own app.
5. *Clients → Create client*, type **Desktop app**. Download the JSON file.
6. On your own computer, run:
   ```bash
   pip install google-auth-oauthlib
   python scripts/google_auth.py ~/Downloads/client_secret_*.json
   ```
   Sign in and grant access. Google should only ask to *see* your calendars and to *manage calendars the app creates*. The script prints three values.

### 3. GitHub secrets

Create these secrets under *Settings → Secrets and variables → Actions*. The safest option is to store them as *environment secrets* in the **`kalender`** environment (*Settings → Environments*, limited to `main`), because any code in the repository can use *repository secrets*:

| Secret | Value |
|---|---|
| `GOOGLE_PERSON_NAME` | First name of the person using Google |
| `ICLOUD_PERSON_NAME` | First name of the person using iCloud |
| `GOOGLE_CLIENT_ID` | from step 2 |
| `GOOGLE_CLIENT_SECRET` | from step 2 |
| `GOOGLE_REFRESH_TOKEN` | from step 2 |
| `ICLOUD_USERNAME` | Apple ID (email) of the iCloud account |
| `ICLOUD_APP_PASSWORD` | from step 1 |

### 4. Test run

*Actions → Synkroniser kalendere → Run workflow*, with **dry run** ticked (the default). Nothing is written; the log shows how many events would be created, changed and deleted. When it looks right, run it once without dry run. After that it runs by itself every 30 minutes.

If one account's secrets are missing, that account is skipped with a warning instead of failing. A dry run still shows what the other account would share, so each side can be tested on its own. Nothing is shared for real until all 7 secrets are set.

The two shared calendars are created automatically on the first real run. Give them a colour in your calendar apps.

The sync job only runs in the repository named in the `if:` line of `.github/workflows/sync.yml`, so public copies and forks don't try to sync without secrets. If you use this code yourself, change it to your own repository.

## Local development

```bash
pip install --require-hashes -r requirements-dev.txt
python -m pytest
python -m calsync --dry-run   # needs the environment variables above
```

Run locally, `--dry-run` also lists each event's time and title.

New packages go in `requirements.in` (or `requirements-dev.in`); regenerate the lock files with the command at the top of `requirements.txt`.
