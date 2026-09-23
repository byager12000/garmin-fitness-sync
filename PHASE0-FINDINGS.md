# Phase 0 — Verified assumptions and incompatibilities

Stack project: **STK-10 Garmin → Notion Fitness Sync**
Date: 2026-09-22 · Verified against the actually-installed packages, not docs alone.

The spec asked Phase 0 to confirm the library, the auth flow, metric
availability, Termux compatibility, and the Notion destination — and to record
what is *unavailable* rather than invent substitutes. Results below.

---

## 1. Garmin library — confirmed, with one important correction

| Item | Verified value |
|---|---|
| Package | `garminconnect` (cyberjunky/python-garminconnect) |
| Version installed | **0.3.16** |
| Python floor | **>= 3.12** (hard requirement) |
| Dependencies | `curl_cffi>=0.15.0`, `requests`, `ua-generator` |
| Maintenance | Active — 0.3.13 released 2026-09-09, 0.3.16 current |
| Status | **Unofficial.** Isolated behind `garmin_client.py`, as the spec requires |

### Correction to the spec's assumption

The spec says to persist tokens using "the library's supported secure token
mechanism". That mechanism **changed**, and the old one is dead:

- **`garth` is deprecated** and 0.3.x no longer uses it at all.
- Verified locally: the `Garmin` object has **no `.garth` attribute** and no
  `.dump()`. Both were central to every pre-0.3 recipe.
- Garth-format token stores are **not readable** by 0.3.x. Upgrading silently
  breaks token resume and surfaces only as a generic `Not authenticated`
  (upstream issue #439).

Any older Garmin+Python example found online will therefore fail. The current
mechanism is a single call:

```python
client = Garmin(email, password, prompt_mfa=callback)
client.login("~/.garminconnect")   # loads tokens, refreshes, or logs in fresh
```

Read from the installed source, `login(tokenstore)`:
1. loads `garmin_tokens.json` from the path if present,
2. proactively refreshes the DI token when it is close to expiry,
3. falls back to email/password **only** if that fails,
4. persists fresh tokens back to the same path.

So one call covers both "reuse the session" and "first login", which is what
`garmin_client.connect()` does.

**MFA:** handled interactively via `prompt_mfa` on first login. For unattended
Phase 5 use, 0.3.16 also exposes `return_on_mfa=True` plus `resume_login(code)`,
which allows a non-interactive flow. Noted for later; not needed now.

---

## 2. ~~⚠️ Termux compatibility~~ — RESOLVED, and this finding was WRONG

> **Correction, 2026-09-23.** `curl_cffi` **builds and runs fine on Termux.**
> It was compiled from source on the S24 Ultra (Android 16, Python 3.14) in a
> few minutes, given `clang` and `libffi`, and the sync has been running
> hourly on the phone since.
>
> What follows was right about *prebuilt wheels* — `pip install --only-binary`
> genuinely fails, there is no Android wheel — but wrong to conclude from that
> that the package is unusable. **None of the workarounds below were needed**,
> including the `proot-distro` Debian option I rated "most promising".
>
> Lesson worth keeping: "platform X is unsupported" in upstream docs and
> issue trackers usually means "we ship no binaries for it", not "it cannot
> work". A 20-minute source build would have settled this on day one, instead
> of it hanging over the project as the main architectural risk.
>
> The section is kept as written because the reasoning was sound given what
> was knowable then, and because the wheel-vs-source distinction is the useful
> part.

**Original finding (superseded):**

`garminconnect` 0.3.x has a hard dependency on **`curl_cffi`**, a C extension
that bundles `libcurl-impersonate`. Its supported platforms are Linux
(x86_64/aarch64 glibc), macOS and Windows. **Android/Termux is not among them:**

- A Termux support request has been open upstream since July 2023 with no
  resolution.
- `termux-packages` carries a separate bug report of `pip install curl_cffi`
  failing on Termux.
- The root cause is structural, not a missing flag: PyPI wheels target glibc,
  while Termux uses Android's Bionic libc, so pip must build from source — and
  the bundled impersonate binaries do not build cleanly there.

**Impact:** Phases 1–4 are unaffected — they run on the Windows laptop, which is
where you will be testing anyway. Phase 5 (hourly on the S24 Ultra) is the part
at risk. The spec's "phone-first, no always-on PC" requirement depends on
resolving this.

**Options to weigh at Phase 5, roughly in order of promise:**

1. **`proot-distro` Debian inside Termux** — gives a real glibc userland on the
   phone, where the standard aarch64 wheel should install normally. Keeps the
   phone-first architecture intact. Most likely to work; costs some battery and
   setup complexity.
2. **Just try it on the S24 Ultra.** Cheap to test, and wheel availability moves.
   Worth 20 minutes before engineering around it.
3. **Build `curl-impersonate` from source in Termux** and point `curl_cffi` at it
   via `LD_LIBRARY_PATH`. Possible, fragile, and a maintenance burden.
4. **Move the runtime off the phone** (small always-on host / cheap VPS /
   scheduled cloud job). Reliable, but contradicts the stated "no always-on PC"
   preference — your call, not mine to make.
5. **Official Garmin Health API.** The spec already names this as the documented
   fallback if the unofficial path proves unreliable. Needs approval, so it is
   not a quick pivot.

I have **not** picked one. It changes the shape of Phase 5 and the decision is
yours.

Termux's own Python is fine: **Python 3.12 is available via `pkg`**, which
satisfies the library's 3.12 floor.

---

## 3a. Metric availability — ANSWERED by the live test, 2026-09-22

First successful run against Ben's real account. **All 13 endpoints returned
data** (`status: OK`, exit code 0, no DATA AVAILABILITY section).

**Available and populated:**

| Group | Confirmed live |
|---|---|
| Today | steps, step goal, distance, active/resting/total calories, intensity minutes, floors, resting HR, stress, Body Battery current/high/low |
| Sleep | duration, score, all four stages (deep/light/REM/awake), overnight HRV, HRV status |
| Recovery | training readiness score + level, recovery time, VO2 max, acute load |
| Activities | type, start, duration, distance, calories, avg/max HR, pace or speed, elevation, training effect, cadence |

**Genuinely unavailable — recorded, not substituted:**

| Metric | Why |
|---|---|
| Training status | `mostRecentTrainingStatus` is `null` on this account today |
| Fitness age | `fitnessAge: null` in Garmin's own `max_metrics` response |
| Weight / BMI / body fat | No connected smart scale. Spec says do not hand-enter these |
| Hydration | Not tracked; normalized to `null` as planned |

**Data-quality note for Phase 3:** Garmin truncates `activityName` at ~45
characters, so Runna's long workout titles arrive already clipped — e.g.
`San Diego - W4 Tue Intervals - Drop Set (2.6`. That happens on Garmin's side,
not ours. ChatGPT will see the clipped names.

### Two bugs the live data exposed

1. **`recoveryTime` is in minutes, not seconds.** Was reporting 0.53 h after an
   interval session; the true value is **31.8 h** (1908 minutes). Confirmed by a
   second readiness record where `recoveryTime: 1` coincides with Garmin's own
   `REACHED_ZERO` / `WELL_RECOVERED` feedback. Fixed.
2. **Training status read a key that does not exist.** The code looked for
   `latestTrainingStatusData` at the top level; the real payload nests it under
   `mostRecentTrainingStatus`. It would have shown `-` even once Garmin
   populated it. Now reads the nested path with the old one as fallback, and
   picks up `acuteLoad` from the readiness record. Fixed.

Also hardened: Garmin returns **several readiness snapshots per day** in
arbitrary order, so the newest is now chosen by timestamp rather than by
trusting entry `[0]`.

### Auth notes from the first real login

- Garmin returned **429 IP rate limited** on two of its login routes before
  falling through to a third that reached the MFA step. Login still succeeded.
  Worth watching before committing to an hourly schedule in Phase 5.
- MFA was required on first login and completed interactively. The second run
  authenticated via stored tokens with **no prompt** — the unattended path is
  proven.
- `sys.stdin.isatty()` cannot be trusted to detect "no one at the keyboard";
  some harnesses report a TTY while stdin is really a null device. The reliable
  signal is catching `EOFError` from `input()`, which now produces a clear
  `AUTH_REQUIRED` message instead of a bare traceback.

---

## 3. Metric availability — original assessment (superseded by 3a)

Every method the spec's metric list needs **exists** on 0.3.16. Verified by
introspecting the installed package (all 24 present with matching signatures):

`get_user_summary` · `get_steps_data` · `get_sleep_data` · `get_hrv_data` ·
`get_body_battery` · `get_training_readiness` · `get_training_status` ·
`get_rhr_day` · `get_all_day_stress` · `get_intensity_minutes_data` ·
`get_floors` · `get_max_metrics` · `get_body_composition` ·
`get_activities_by_date` · `get_activity_details` · `get_weigh_ins` …

What **cannot** be determined from here is which of them actually return data
for your account and watch — that depends on the device, your Garmin settings,
and whether a metric was recorded at all. Rather than guess, the program
measures it: every endpoint is called defensively and the run reports a
`DATA AVAILABILITY` section plus `unavailable_endpoints` / `empty_endpoints` in
the JSON.

**That is the actual Phase 1 test.** Your first run tells us, from your real
account, exactly which metrics are live. Anything that comes back empty gets
recorded here rather than substituted with a stand-in value.

Known-uncertain going in:
- **Hydration** — spec already flags it as unreliable; normalized to `null`
  unless it genuinely appears. Never a dependency.
- **Body composition** — only present if you have a compatible scale; the spec
  is explicit that you should not hand-enter values to satisfy the sync.
- **Training readiness / HRV status / VO2 max / fitness age** — newer-watch
  metrics; present on a Forerunner/Epix-class device, absent on older ones.

---

## 4. Notion destination — does not exist yet

- Searched The Nexus: **there is no `Fitness Live` page.** It has to be created.
- **Recommendation:** create it as a child of **Cut to 180 — Coaching System**
  in The Nexus. That page is already ChatGPT's durable fitness/coaching context
  (Daily Log, Food Log, Coaching Patterns), and `Fitness Live` is the missing
  objective-activity half of exactly that picture. Putting it there means one
  retrieval context rather than two.
- **Permission model:** the sync will need its own Notion **internal integration
  token**, and the `Fitness Live` page must be explicitly shared with that
  integration. Minimal permissions: update content on that one page. Nothing
  else in The Nexus needs to be exposed.
- **You have to create the integration** — I cannot mint a Notion token. That is
  a Phase 3 prerequisite, not a Phase 1 blocker.

Note: the Notion connector used in this session is *your* account's, not the
sync's. The unattended script needs its own token.

---

## 5. Smaller things found and fixed

- **Windows has no IANA timezone database.** `ZoneInfo("America/New_York")`
  raised `ZoneInfoNotFoundError` on this laptop. Added the `tzdata` package, and
  made a bad/unusable `FITNESS_TZ` fall back to the system zone with a warning
  instead of taking the sync down. The default path (follow the device's own
  timezone) never needed it.
- **Cycling paces were nonsense.** A 16 mph ride rendered as `3:45/mi`. Pace in
  min/mile is now only emitted for foot sports; everything else reports
  `avg_speed_mph`. Both fields exist in the schema.
- **Project layout** is flat (`sync_garmin.py` at the root), not an installable
  package, so Phase 5 can launch it directly from `run_sync.sh`.

---

## 6. Assumptions carried into Phase 1

1. Read-only throughout. No method that writes to Garmin is called anywhere.
2. `schema_version: 1` — the normalized contract is explicit and versioned, so
   Garmin changes do not reach Notion formatting directly.
3. The day boundary follows the **device's current timezone**, resolved at
   runtime, so travel does not create duplicate or missing days.
4. Missing data is always `null` — never `0`, never a substitute.
5. One failing optional endpoint must never kill the run.
6. Phase 1 writes **nothing** to disk except the Garmin token store the library
   manages itself. `latest.json` is Phase 2.
