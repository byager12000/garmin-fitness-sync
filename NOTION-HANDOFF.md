# Notion handoff log — STK-10

Audit trail of everything pulled from and proposed back to Notion for this
project, following the same convention as the CLICK PLC projects.

---

## 2026-09-22 — Phase 0 + Phase 1

### Pulled from Notion (read-only)

| Page | Project ID | Why |
|---|---|---|
| [Human SOP — Claude ↔ CLICK PLC Workflow](https://app.notion.com/p/3e1cbcedeeca8132ac21f7e83daa45e9) | STK-5 | Standing procedure; read before any project work |
| [AI Operating Procedure — ChatGPT / Notion / Claude](https://app.notion.com/p/3e0cbcedeeca819f8fd8d2640d2af0f5) | STK-8 | Roles, boundaries, handoff contract |
| [AI Dev Environment & Tooling](https://app.notion.com/p/3e1cbcedeeca8169b190cfd1eb2d20d1) | STK-4 | Shared toolchain (uv / Python 3.12 conventions) |
| [Garmin → Notion Fitness Sync](https://app.notion.com/p/3e3cbcedeeca8129993ae02876146648) | **STK-10** | The spec. Treated as source of truth |
| [Cut to 180 — Coaching System](https://app.notion.com/p/3e1cbcedeeca8120808df3bc26628b95) | — | Destination context for `Fitness Live` |

Searched The Nexus for an existing **`Fitness Live`** page: **none exists.**

### Authorization

The STK-10 page ends with an explicit handoff: *"Begin with Phase 0, document
any assumptions or incompatibilities you find, then implement Phase 1 only.
Stop after Phase 1."* That is the scope of this session.

Per STK-8, no physical-machine action applies here; this project has no PLC
element. The Garmin side is read-only by design.

### Written to Notion — applied 2026-09-22 on Ben's go-ahead

Updated the **STK-10 Stack row** ([link](https://app.notion.com/p/3e3cbcedeeca8129993ae02876146648)):

| Property | Change |
|---|---|
| **Phase** | Architecture → **Programming** |
| **Revision** | Rev 0 → **Rev 0 — Phase 1** |
| **Current Focus** | Phase 0 verified, Phase 1 delivered, awaiting Ben's live run; Phase 5 runtime decision open |
| **Critical Questions** | Split into ANSWERED (library, auth, garth deprecation, Termux Python) and OPEN (runtime location, real metric coverage, Notion integration) |
| **Current Architecture** | Added local project path, adapter isolation, versioned schema, read-only audit result |
| **Notes** | Recorded the `garth` deprecation and the `curl_cffi`/Termux incompatibility |
| **AI Handoff Summary** | Rewritten so the next session knows the state and that the next action is Ben's |

Appended a **Claude report — Phase 0 + Phase 1** section to the page body,
covering verified assumptions, the unresolved Phase 5 runtime issue, metric
availability, the Notion destination, what was built, validation performed,
defects found, assumptions carried forward, and Ben's next actions — per the
writeback requirements in STK-8.

Gotcha worth remembering: Notion **text properties are parsed as markdown**.
Windows paths lost their backslashes (`C:\Visron\...` → `C:Visron...`) and
`.py` filenames were auto-linked as URLs (`.py` is a valid TLD). Wrapping such
tokens in backticks fixes both. Corrected on a second pass and verified.

### Still not done (Ben's to do)

- **`Fitness Live` page** — not created. Recommended location: child of
  *Cut to 180 — Coaching System* in The Nexus.
- **Notion internal integration token** scoped to that single page. Claude
  cannot mint one. Phase 3 prerequisite.

### Local artifacts

`C:\Visron\App Dev\garmin-fitness-sync` — git repository initialized by
`uv init`, **not committed**. Per the standing rule, Claude commits and pushes
only when Ben says so.

---

## 2026-09-22 (later) — Phase 1 live test result

### Written to Notion

Updated the **STK-10 Stack row** again after the live test:

- **Current Focus** → Phase 1 PASSED; ready for Phase 2 on Ben's go-ahead.
- **Critical Questions** → metric coverage moved from OPEN to ANSWERED, with
  the confirmed available/unavailable lists. Added the Garmin 429 rate-limit
  observation as a new open item for Phase 5.
- **AI Handoff Summary** → records Phase 1 acceptance (status OK, exit code 0,
  token reuse with no MFA) and names Phase 2 as the next step.

Appended a **Phase 1 test result — PASSED** section to the page body: metric
coverage table, the two bugs live data exposed, auth observations for Phase 5,
and the activity-name truncation note for Phase 3.

### Still not done (Ben's to do)

- `Fitness Live` page and its scoped Notion integration token (Phase 3).
- The Phase 5 runtime decision (`curl_cffi` on Termux).

---

## 2026-09-22 (Phase 2) — persistence built, Stack updated

### Written to Notion

STK-10 Stack row: **Revision** → `Rev 0 — Phase 2`; **Current Focus** and
**AI Handoff Summary** updated for Phase 2 and the commit IDs; **Critical
Questions** gained the resolved 429 explanation (cell hotspot / carrier-grade
NAT, login endpoints only) and a new open item about the missing GitHub remote.

Appended a **Phase 2 — local persistence** section to the page body.

### Committed

- `6c264e2` Phase 1 — read-only fetch, normalize, console output
- `8bf5bc8` Phase 2 — persistence with last-good preservation

`.env`, `data/` and `logs/` are gitignored and confirmed absent from both
commits. **No GitHub remote is configured**, so the laptop is the only copy.

### Still blocking Phase 3 (Ben's to do)

- Create the `Fitness Live` page in The Nexus.
- Create a Notion internal integration token scoped to that one page.

---

## 2026-09-22 (later) — GitHub remote created

Remote wired and pushed on Ben's go-ahead:
`https://github.com/byager12000/garmin-fitness-sync.git` (private), branch
`main` tracking `origin/main`, 3 commits.

Naming note: PLC projects use the `plc-<name>` prefix; this is an App Dev
project, so it is just `garmin-fitness-sync`.

Verified after push that `.env`, `data/` and `logs/` are absent from the
remote tree. GitHub is now the off-laptop copy, per the standing rule that
`C:\Visron` is not in OneDrive.

---

## 2026-09-22 (Phase 3) — Notion write, verified end to end

### Created in Notion

**Fitness Live** page, under *Cut to 180 — Coaching System* in The Nexus:
`https://app.notion.com/p/3e3cbcedeeca81009ff6d2f9219d2e15`

Structure: permanent intro (a "managed page, do not edit by hand" callout plus
a description) above a divider; everything below the divider is the managed
section the sync replaces each run.

Ben created the internal integration and connected it to that one page.
Verified the token sees **exactly one page** — nothing else in the Nexus is
exposed to it.

### Verified

- First live end-to-end sync: exit 0, 44 managed blocks written.
- **Idempotency**: after three consecutive syncs the page holds 47 blocks
  (3 permanent + 44 managed) with exactly 6 headings and no duplicates.
  Satisfies acceptance criterion 8.
- **Notion failure path**: forced a 401 with a bad token. Result — exit 4
  (`NOTION_UNAVAILABLE`), Garmin data still saved locally, and the Notion page
  left untouched at 47 blocks rather than being half-written.

### Still open

- Phase 4 (hardening) and Phase 5 (Android automation) not started.
- The Phase 5 runtime decision (`curl_cffi` has no Android/Termux support).

---

## 2026-09-22 (Phase 4) — hardening

Built and verified. Nothing new written to Notion beyond the STK-10 Stack row.

Added `runlock.py`; retry/backoff in `notion_client.py`; log rotation in
`storage.py`; mid-run token-expiry handling in `garmin_client.py`.

Verified by 10 offline checks plus a real two-process concurrency test: one
sync completed and published while the second printed SKIPPED and exited 0,
the lock was cleaned up, and the page stayed at 47 blocks with no duplicates.

Notable platform gotcha recorded in the README: `os.kill(pid, 0)` is a
harmless liveness probe on POSIX but calls `TerminateProcess` on Windows, so
the lock's PID check is POSIX-only and lock age is the cross-platform
fallback.

---

## 2026-09-23 — Phase 5 INSTALLED ON THE PHONE

Set up the S24 Ultra (Android 16) end to end over adb. The sync now runs
hourly on the phone and updates Fitness Live itself.

### Outcome

- `curl_cffi` **builds from source on Termux** — the Phase 0 finding that
  Android was unsupported held for wheels only. No proot-distro needed.
- Python 3.14.6, all deps, project files and credentials installed.
- Garmin token copied from the laptop rather than logging in: no MFA, no 429,
  and **no Garmin password on the phone**.
- Hourly job registered via `termux-job-scheduler`
  (`PERIODIC: interval=+1h0m0s0ms`), verified by forcing a run.
- The single-instance lock proved itself in the wild: two invocations
  overlapped and the second exited 0 with SKIPPED.

### Written to Notion

Created **Fitness Live** earlier; it is now being updated by the phone.
Verified 48 blocks, 6 headings, no duplicates, status OK.

### Documented

`PHONE-SETUP.md` (the adb procedure that worked, with every gotcha) and
`bootstrap-phone.sh` (one-shot Termux setup). TERMUX-SETUP.md marked as
superseded.

---

## 2026-09-23 (later) — reboot finding + readable timestamps

### Reboot: the job did NOT survive

Confirmed empirically. After Ben rebooted, `termux-job-scheduler --pending`
came back empty — periodic JobScheduler jobs are not persisted on Android 16.
The battery exemption, standby bucket and phantom-process setting all DID
survive.

Fixed by installing **Termux:Boot** and adding `~/.termux/boot/00-garmin-sync.sh`,
which re-registers the job at every boot and logs to `logs/boot.log`.
Documented in PHONE-SETUP.md §8 and automated in bootstrap-phone.sh.

Worth noting an earlier claim of mine was wrong: I briefly said the job had
survived, based on a fresh Notion timestamp that was actually my own forced
run from *before* the reboot. Corrected on checking properly.

### Readable timestamps on the page

Ben pointed out the page had no usable timestamp — it read
`Last success 2026-09-23T05:37:20.414643-07:00`, which is useless when the
question is just "did it run recently". Now renders as
`Wed 23 Sep, 5:54 AM PDT (just now)`, with explicit last-success /
last-attempt / data-date rows, plus "Figures as of ..." under Today because
those values accumulate through the day.
