# Garmin → Notion Fitness Sync

Stack project **STK-10**. Read-only sync that turns Garmin Connect data into a
compact, normalized record ChatGPT can use for nutrition, training and recovery
context — with no manual reporting.

**Current state: Phase 1 complete.** Logs in to Garmin, fetches today plus a
rolling activity window, normalizes it, and prints a readable summary and the
normalized JSON. Nothing is written to Notion yet, and nothing is written back
to Garmin ever.

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

Exit codes (provisional — Phase 4 finalizes them):

| Code | Meaning |
|---|---|
| `0` | `OK` — everything fetched |
| `10` | `PARTIAL` — some endpoints failed, the rest is good |
| `2` | `AUTH_REQUIRED` — no usable token and login failed |
| `3` | `GARMIN_UNAVAILABLE` — every endpoint failed |
| `1` | `FAILED` — unexpected error |

---

## What to look at on the first run

The summary ends with a **DATA AVAILABILITY** section listing endpoints that
failed or came back empty. That is the real output of this phase: it tells us,
from your actual account and watch, which of the spec's metrics exist. Anything
empty gets recorded in PHASE0-FINDINGS.md rather than replaced with a made-up
value.

---

## Layout

```
garmin-fitness-sync/
├── sync_garmin.py       entry point: login → fetch → normalize → print
├── garmin_client.py     the ONLY file that touches the garminconnect package
├── normalize.py         raw Garmin → versioned schema, US units
├── config.py            env, token store, timezone resolution
├── .env.example
├── PHASE0-FINDINGS.md   verified assumptions + the Termux decision
└── README.md
```

`garmin_client.py` is the isolation layer the spec asks for: the unofficial
Garmin API is called there and nowhere else, so an upstream change is contained
to one file.

Arriving in later phases: `data/latest.json` and logging (Phase 2),
`notion_client.py` (Phase 3), retry/backoff and locking (Phase 4),
`run_sync.sh` and Tasker scheduling (Phase 5).

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
