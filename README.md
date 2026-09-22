# Garmin → Notion Fitness Sync

Stack project **STK-10**. Read-only sync that turns Garmin Connect data into a
compact, normalized record ChatGPT can use for nutrition, training and recovery
context — with no manual reporting.

**Current state: Phase 5 built — all phases complete, pending the on-phone
install.** Logs in to Garmin, fetches today plus a rolling activity window,
normalizes it, saves the snapshot to `data/latest.json`, and updates the
**Fitness Live** page in The Nexus so ChatGPT can read it. Nothing is ever
written back to Garmin.

For hourly running on Android, see **[TERMUX-SETUP.md](TERMUX-SETUP.md)**.

Read [PHASE0-FINDINGS.md](PHASE0-FINDINGS.md) first — it records what was
verified, and one decision about the phone runtime that is waiting on you.

---

## Setup

One-time, in this folder:

```bash
uv sync
```

Then create your `.env` from the template and fill in the Garmin credentials:

```bash
cp .env.example .env
```

`GARMIN_EMAIL` and `GARMIN_PASSWORD` are needed **only for the first login**.
After that the session token is cached in `~/.garminconnect` and reused.

---

## Run it

First run — this one is interactive, because Garmin may ask for an MFA code:

```bash
uv run python sync_garmin.py
```

Every run after that should need nothing from you.

| Command | What it prints |
|---|---|
| `uv run python sync_garmin.py` | human summary **and** normalized JSON |
| `uv run python sync_garmin.py --summary` | just the readable summary |
| `uv run python sync_garmin.py --json` | just the normalized JSON |
| `uv run python sync_garmin.py --days 14` | widen the activity window |
| `uv run python sync_garmin.py --verbose` | add debug logging on stderr |
| `uv run python sync_garmin.py --no-write` | run without touching `data/latest.json` |
| `uv run python sync_garmin.py --no-notion` | fetch and save locally, skip the Notion update |
| `uv run python sync_garmin.py --ignore-lock` | run even if another sync holds the lock (debugging) |

Exit codes (provisional — Phase 4 finalizes them):

| Code | Meaning |
|---|---|
| `0` | `OK` — everything fetched |
| `10` | `PARTIAL` — some endpoints failed, the rest is good |
| `2` | `AUTH_REQUIRED` — no usable token and login failed |
| `3` | `GARMIN_UNAVAILABLE` — every endpoint failed |
| `4` | `NOTION_UNAVAILABLE` — Garmin data saved, but the page update failed |
| `1` | `FAILED` — unexpected error |

---

## What to look at on the first run

The summary ends with a **DATA AVAILABILITY** section listing endpoints that
failed or came back empty. That is the real output of this phase: it tells us,
from your actual account and watch, which of the spec's metrics exist. Anything
empty gets recorded in PHASE0-FINDINGS.md rather than replaced with a made-up
value.

---

## What persistence guarantees (Phase 2)

`data/latest.json` holds the last known good snapshot. The rules it enforces:

- **Atomic writes.** The file is written to a temp file in the same folder and
  then renamed, so an interrupted run can never leave a half-written snapshot
  where good data used to be.
- **A failed sync never erases working data.** If login fails entirely, the
  previous data is kept and only the `sync` block is updated — status, a
  non-sensitive error, and `last_attempt`.
- **`last_success` only advances on an actual success**, so you can always
  tell how old the data really is.
- **Stale sections are labelled, not hidden.** If every endpoint behind a
  section fails, that section is carried over from the last good sync and
  listed in `sync.stale_sections` (and in the summary's DATA AVAILABILITY
  block). A section that got a *partial* answer keeps its fresh data instead.
- **A corrupt snapshot is survivable** — it is ignored rather than crashing.

`logs/sync.log` records each run's status, which endpoints failed or were
empty, and which sections were stale. No secrets are ever logged. Log rotation
is Phase 4.

## Running it on the phone (Phase 5)

Full walkthrough: **[TERMUX-SETUP.md](TERMUX-SETUP.md)**. The short version:

- `run_sync.sh` is the single launch entry point. It runs **one** sync and
  exits — no resident loop, which Android's Doze would kill anyway.
- Tasker fires it hourly through the Termux:Tasker plugin.
- **Do not log in to Garmin on the phone.** Copy
  `~/.garminconnect/garmin_tokens.json` across from the laptop instead. It is
  three opaque strings with no device binding, so the phone inherits an
  already-authenticated session — which skips both the MFA prompt and the
  per-IP 429 throttle that only ever affects the login endpoints.
- The one genuine unknown is `curl_cffi`, which has no official Android
  support. Try `pip install curl_cffi` first; if it fails, `proot-distro`
  Debian gives a glibc userland on the phone where the normal wheel installs.

## Hardening (Phase 4)

What makes this safe to run unattended every hour:

- **Single-instance lock.** `run.lock` stops two syncs racing each other into
  the same snapshot and the same Notion page. An overlapping run exits **0**
  with `SKIPPED` — overlap is normal for a scheduler, not a failure, so it
  does not raise an alarm. The lock is released even if the run crashes.
- **Stale lock recovery.** A killed process or a hard reboot leaves the file
  behind, so a lock older than 30 minutes is reclaimed automatically. You
  should never have to delete it by hand.
- **Retry with bounded backoff** on Notion calls: 4 attempts, exponential with
  jitter, capped at 16 s, honouring `Retry-After`. Only transient conditions
  (429, 5xx, connection errors) retry — **401/403/404 fail fast**, because a
  bad token or a missing page will never succeed on a retry.
- **Mid-run token expiry** is handled: one silent re-login, then the failed
  endpoint is retried. Exactly one, never a loop — repeatedly retrying an auth
  failure is how accounts get rate-limited or locked.
- **Log rotation**, 512 KB × 4 files, so an hourly job cannot fill the phone.
- Garmin calls rely on the library's own bounded retry rather than being
  wrapped in a second one, which would multiply into a burst against an API
  that already rate-limits by IP.

> **A note on the lock and Windows.** The obvious way to check whether the
> holding process is still alive is `os.kill(pid, 0)`. On POSIX that is a
> harmless probe. On Windows, Python's `os.kill` has no signal semantics — it
> calls `TerminateProcess`, so that "probe" would *kill* the process it was
> asking about. The PID check is therefore POSIX-only, and lock age is the
> cross-platform fallback.

## The Notion page (Phase 3)

The sync updates one page in place — **Fitness Live**, under *Cut to 180 —
Coaching System* in The Nexus. It never creates a second page.

The page has a **managed section**: everything below the first divider. Each
run replaces that section, so the page never grows without bound. Anything you
write *above* the divider is yours and survives every sync.

Headings are fixed, because ChatGPT retrieval depends on them not moving:
`Sync status` · `Today` · `Sleep and recovery` · `Today's activities` ·
`Last 7 days` · `Machine-readable snapshot`.

Replacement is **append-then-delete** on purpose. Notion has no transactions,
so if the delete step fails the page shows duplicated content — visible and
fixable — rather than being left empty, which deleting first would risk.

Ordering guarantees:

- The local snapshot is saved **before** publishing, so a Notion outage never
  costs Garmin data that was already fetched.
- A Notion failure reports `NOTION_UNAVAILABLE` (exit 4), distinct from a
  Garmin failure. The next run simply republishes.
- A **failed Garmin run still updates the page**, showing the failure status
  while preserving the previously good data. A silently stale page is worse
  than one that says it is stale.

### Setting up the Notion side

1. Create an internal integration at
   [notion.so/my-integrations](https://www.notion.so/my-integrations) with
   **Read content** and **Update content** only, and no user information.
2. Open the `Fitness Live` page → `•••` → **Connections** → connect the
   integration. An integration can only see pages explicitly shared with it,
   so this step is what grants access — and connecting only this page means
   the token cannot read anything else in the Nexus.
3. Put the secret in `.env` as `NOTION_TOKEN=ntn_...`.

## Layout

```
garmin-fitness-sync/
├── sync_garmin.py       entry point: login → fetch → normalize → save → print
├── garmin_client.py     the ONLY file that touches the garminconnect package
├── normalize.py         raw Garmin → versioned schema, US units
├── storage.py           atomic snapshot writes, last-good preservation, logging
├── notion_client.py     the ONLY file that calls the Notion API
├── notion_page.py       snapshot → Notion page layout (stable headings)
├── runlock.py           single-instance lock, with stale-lock recovery
├── config.py            env, token store, Notion settings, timezone resolution
├── run_sync.sh          single launch entry point for Tasker / Termux
├── requirements.txt     pinned deps for environments without uv (the phone)
├── TERMUX-SETUP.md      hourly Android setup, battery settings, troubleshooting
├── data/latest.json     last known good snapshot (gitignored)
├── logs/sync.log        run log (gitignored)
├── .env.example
├── PHASE0-FINDINGS.md   verified assumptions + the Termux decision
└── README.md
```

`garmin_client.py` is the isolation layer the spec asks for: the unofficial
Garmin API is called there and nowhere else, so an upstream change is contained
to one file.

All phases are now built. What remains is installing it on the phone and
confirming it survives a few days of hourly running.

---

## Security

- Secrets live in `.env` (gitignored). No password or token is hard-coded.
- Garmin session tokens are cached by the library in `~/.garminconnect`; on a
  shared machine, tighten with `chmod 700 ~/.garminconnect` and
  `chmod 600 ~/.garminconnect/*`.
- Nothing in this program prints or logs a password, token or cookie.
- The Garmin side is strictly read-only — no workout, profile or device data is
  ever modified.

---

## Known risks

`garminconnect` is an **unofficial** Garmin Connect client. Garmin can change
or block it without notice; the deprecation of `garth` mid-2026 is a recent
example. This is why everything Garmin-specific is behind one adapter and the
normalized schema is versioned. The official Garmin Health API remains the
documented fallback.

The phone runtime (`curl_cffi` on Termux) has an open question — see
PHASE0-FINDINGS.md §2.
