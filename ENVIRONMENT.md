# Environment and toolchain

Two machines run this project. They are deliberately different, and knowing
which is which explains most surprises.

| | **Phone — the runtime** | **Laptop — development** |
|---|---|---|
| Device | Galaxy S24 Ultra, Android 16 (SDK 36), arm64 | Windows 11 |
| Runs | Termux + Termux:API + Termux:Boot | uv project |
| Python | 3.14.6 (Termux `pkg`) | 3.12.10 (via uv) |
| Deps | `pip` into Termux's Python, no venv | `uv sync` against `uv.lock` |
| Schedule | `termux-job-scheduler`, hourly | none — run by hand |
| Timezone | `America/Los_Angeles` | Eastern |
| Project path | `~/garmin-fitness-sync` | `C:\Visron\App Dev\garmin-fitness-sync` |

**The phone is the real runtime.** The laptop is where code is written, tested
and committed; running a sync there is fine but writes the page with the
laptop's timezone (see below).

## Laptop

`uv` is the package manager, consistent with the CLICK PLC projects. It is
**not on PATH in a fresh PowerShell** — a known quirk on this machine:

```powershell
$env:Path = "C:\Users\byage\.local\bin;" + $env:Path
```

Common commands, from the project folder:

```powershell
uv sync                                   # install/refresh dependencies
uv run python sync_garmin.py --summary    # one sync, human-readable
uv run python sync_garmin.py --no-notion  # fetch and save locally only
```

`tzdata` is a real dependency here, not incidental: Windows ships no IANA
timezone database, so `ZoneInfo("America/New_York")` raises without it.

## Phone

No virtual environment — Termux's Python is already per-app isolated, and
`curl_cffi` was compiled into it. `run_sync.sh` therefore falls through to
plain `python3`, which is the intended path.

`curl_cffi` **has no Android wheel and must build from source.** It works;
budget a few minutes. `clang` and `libffi` must be installed first.

Full setup, including every trap: **[PHONE-SETUP.md](PHONE-SETUP.md)**.

## adb

Installed on the laptop with `winget install Google.PlatformTools`, and not on
PATH either. Full path:

```
C:\Users\byage\AppData\Local\Microsoft\WinGet\Packages\Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe\platform-tools\adb.exe
```

Only needed when changing something on the phone. **USB debugging is off** in
normal use and must be re-enabled first. Note it also switches itself off after
a reboot, which presents convincingly as a dead USB cable.

Drive adb from **PowerShell, not Git Bash** — Git Bash's MSYS path conversion
mangles Android paths like `/data/local/tmp/x.sh` into Windows paths.

## Versions pinned

| Package | Version | Why it matters |
|---|---|---|
| `garminconnect` | 0.3.16 | Requires Python ≥ 3.12. 0.3.x dropped `garth` entirely |
| `curl_cffi` | 0.16.3 | Hard dependency of garminconnect; the Android build question |
| `python-dotenv` | 1.2.3 | `.env` loading |
| `tzdata` | 2026.4 | Needed on Windows only |
| `requests` | 2.34.2 | Used directly by the Notion adapter |

`uv.lock` is authoritative on the laptop; `requirements.txt` exists for the
phone, which has no uv. **Keep them in step.**

## Known issues

- **`garth` is deprecated.** `garminconnect` 0.3.x builds its own client and
  token store. Any pre-0.3 recipe found online fails with a generic
  `Not authenticated`. There is no `.garth` attribute any more.
- **Garmin rate-limits logins by IP.** A 429 on a cell hotspot is
  carrier-grade NAT, not the account. It affects **login endpoints only** —
  token-based runs have never produced one. Avoid fresh logins on cellular;
  copy the token instead.
- **Line endings.** `core.autocrlf` is true here, so `.gitattributes` forces
  LF on `*.sh`. A CRLF shebang makes Android hunt for an interpreter literally
  named `bash\r`.
- **Notion text properties are parsed as markdown.** Windows paths lose their
  backslashes and `.py` filenames get auto-linked (`.py` is a valid TLD). Wrap
  such tokens in backticks when writing to Stack.
