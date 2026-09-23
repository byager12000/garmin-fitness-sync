# Phase 5 — running the sync hourly on Android (manual route)

> **Superseded by [PHONE-SETUP.md](PHONE-SETUP.md)**, which documents the
> adb-driven procedure that was actually used and works. Keep this one only if
> you want to type everything on the phone itself.
>
> Two things below are now known to be wrong: `curl_cffi` **does** build on
> Termux, so the proot-distro path in §3 is unnecessary; and Tasker is not
> needed at all — `termux-job-scheduler` from Termux:API handles the hourly
> trigger.

Target: Samsung Galaxy S24 Ultra, Termux + Tasker.

Work through this in order. **Step 3 is the risky one** — it's where the
`curl_cffi` question gets settled. Everything before it is safe, and
everything after it is straightforward.

You can do all of this on your **cell hotspot**. See §9 for why, and for the
one thing to avoid.

---

## 1. Install the apps

Install from **F-Droid, not the Play Store** — the Play Store builds of Termux
are abandoned and will fail in confusing ways.

| App | Where |
|---|---|
| Termux | F-Droid |
| Termux:Tasker | F-Droid (plugin — install *after* Termux) |
| Tasker | Play Store (paid) |

Open Termux once after installing so it finishes unpacking, then:

```bash
pkg update && pkg upgrade
```

## 2. Install Python and build tools

```bash
pkg install python python-pip git binutils build-essential libffi openssl
```

Check the version — the project needs **3.12 or newer**:

```bash
python3 --version
```

## 3. The moment of truth — `curl_cffi`

`garminconnect` hard-requires `curl_cffi`, a C extension that bundles
`libcurl-impersonate`. Its supported platforms are Linux/macOS/Windows;
Android is not officially among them, because Termux uses Android's Bionic
libc rather than glibc, so the prebuilt wheels don't apply.

**Try it anyway — it costs 5 minutes and wheel availability moves:**

```bash
pip install curl_cffi
```

### If that succeeds → take path A

```bash
cd ~
git clone https://github.com/byager12000/garmin-fitness-sync.git
cd garmin-fitness-sync
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Then go to §4.

### If it fails → take path B (proot-distro Debian)

This gives you a real glibc userland *on the phone*, where the normal aarch64
wheel installs cleanly. It keeps the phone-first architecture intact — it is
not a retreat to running things on a PC.

```bash
pkg install proot-distro
proot-distro install debian
proot-distro login debian
```

You are now inside Debian. Continue there:

```bash
apt update && apt install -y python3 python3-venv python3-pip git
cd ~
git clone https://github.com/byager12000/garmin-fitness-sync.git
cd garmin-fitness-sync
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

With path B, every later command runs **inside** the Debian session, and the
Tasker command in §7 gains a `proot-distro login debian -- ` prefix.

> Path B costs a few hundred MB and a little battery per run. Path A is
> better if it works, which is the only reason to try it first.

## 4. Move the Garmin token across — do NOT log in on the phone

The phone does not need to log in to Garmin at all, and it is better if it
doesn't: a fresh login is the one operation that can hit Garmin's per-IP 429
throttle, and it would also trigger an MFA prompt.

Instead, copy the already-working session from the laptop.

**On the laptop**, the file is:

```
C:\Users\byage\.garminconnect\garmin_tokens.json
```

Get it onto the phone however is easiest — email it to yourself, Google Drive,
USB cable. It is small (about 2 KB).

**On the phone**, put it in place:

```bash
pkg install termux-api      # only needed once, for storage access
termux-setup-storage        # grant the permission prompt
mkdir -p ~/.garminconnect
cp /sdcard/Download/garmin_tokens.json ~/.garminconnect/
chmod 700 ~/.garminconnect
chmod 600 ~/.garminconnect/garmin_tokens.json
```

> **This file is a live credential** — it grants access to your Garmin
> account. Delete it from Downloads, and from whatever you used to transfer
> it (the email, the Drive folder), once the copy is in place.

## 5. Create the `.env`

```bash
cd ~/garmin-fitness-sync
cp .env.example .env
nano .env
```

Fill in:

```
NOTION_TOKEN=ntn_your_token
NOTION_PAGE_TITLE=Fitness Live
ACTIVITY_LOOKBACK_DAYS=7
```

You can leave **`GARMIN_EMAIL` and `GARMIN_PASSWORD` blank** — the copied
token is what authenticates. Leaving them out means no password sits on the
phone at all, which is the safer arrangement.

Save with `Ctrl+O`, `Enter`, then `Ctrl+X`.

## 6. Test it by hand

```bash
chmod +x run_sync.sh
./run_sync.sh
```

What you should see:

- `Authenticated via stored tokens` — the copied token worked, **no MFA prompt**
- the usual snapshot
- `Notion page updated (Fitness Live)`

Check the Fitness Live page in Notion — the `Last attempt` timestamp should be
seconds old.

If you get `AUTH_REQUIRED`, the token copy didn't land. Re-check the path in
§4 rather than logging in on the phone.

## 7. Schedule it hourly with Tasker

**Profile:**
1. Tasker → **Profiles** tab → **+** → **Time**
2. From **00:00** to **23:59**, tick **Repeat**, every **1 hour**
3. Back out → **New Task** → name it `Garmin Sync`

**Action:**
1. **+** → **Plugin** → **Termux:Tasker**
2. Tap the pencil to configure:
   - **Executable**: `run_sync.sh`
   - **Arguments**: leave empty
   - **Working Directory**: leave empty
   - **Stdin**: leave empty
   - **Terminal**: **unchecked** ← important, otherwise it opens a window every hour
3. Back out and accept

**Termux:Tasker only runs scripts from one specific folder**, so link it:

```bash
mkdir -p ~/.termux/tasker
ln -sf ~/garmin-fitness-sync/run_sync.sh ~/.termux/tasker/run_sync.sh
chmod +x ~/.termux/tasker/run_sync.sh
```

**Path B (proot) users:** a symlink won't work, because the script must run
inside Debian. Create a wrapper instead:

```bash
cat > ~/.termux/tasker/run_sync.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
proot-distro login debian -- bash -c "cd ~/garmin-fitness-sync && ./run_sync.sh"
EOF
chmod +x ~/.termux/tasker/run_sync.sh
```

Test the whole chain by long-pressing the task in Tasker and choosing **Run**.

## 8. Stop Android from killing it

Android will suspend both apps otherwise, and the job will silently stop
running — usually a day or two later, which makes it hard to diagnose.

**Settings → Apps → Termux → Battery → Unrestricted.** Repeat for **Tasker**
and **Termux:Tasker**.

Samsung specifically, this one catches people out:
**Settings → Battery and device care → Battery → Background usage limits** →
make sure Termux and Tasker are **not** in *Sleeping apps* or *Deep sleeping
apps*.

Also: **Settings → Apps → Termux → Battery → Allow background activity.**

Skip the wake lock (`termux-wake-lock`) for now. An hourly job that takes a
few seconds shouldn't need one, and it costs battery continuously. Only add it
if §10 shows runs actually being cut off mid-flight.

## 9. Reboot resilience

Tasker restores time profiles after a reboot by itself, provided it is allowed
to start on boot — which the battery settings in §8 cover.

Verify it properly: reboot the phone, wait for the next hour boundary, and
check that `Last attempt` on the Notion page has moved.

## 10. Checking it is actually working

Three ways, cheapest first:

**The Notion page.** `Last attempt` should never be more than about an hour
old. That single field is the health check.

**The launcher log** — one line per run, including runs that failed before
Python even started:

```bash
tail -20 ~/garmin-fitness-sync/logs/run_sync.log
```

**The app log** — what each run actually did:

```bash
tail -40 ~/garmin-fitness-sync/logs/sync.log
```

## 11. About the hotspot

You can do all of the above on cellular. The 429 rate limiting Garmin applied
earlier came from carrier-grade NAT — your hotspot's public IP is shared with
many other subscribers — and it **only affects the login endpoints**.

- Installing packages: unrelated to Garmin. Fine on cellular.
- Hourly syncs: token-based, never touch the login endpoint. Fine on cellular.
- **A fresh Garmin login: the one thing to avoid on cellular** — which §4
  sidesteps entirely by copying the token instead.

If the token ever does expire unrecoverably, redo §4 from the laptop rather
than logging in on the phone.

## 12. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `AUTH_REQUIRED` on the phone | The token file isn't where the sync looks. Check `ls -la ~/.garminconnect/`. |
| `429 IP rate limited` | Only happens during a fresh login. Don't retry in a loop — wait, and prefer copying the token from the laptop. |
| `NOTION_UNAVAILABLE` (exit 4) | Garmin data was still saved locally. Usually transient; the next run republishes. If it persists, confirm the integration is still connected to the page. |
| `SKIPPED: another sync is already running` | Normal and harmless — the previous run hadn't finished. Exits 0 by design. |
| Nothing runs after a day or two | Battery optimisation. Re-check §8; Samsung's *Sleeping apps* list is the usual culprit. |
| `pip install curl_cffi` fails | Expected on native Termux. Use path B in §3. |
| Tasker action does nothing | The script must be in `~/.termux/tasker/` and be executable. Re-run the `ln -sf` and `chmod +x` from §7. |
| Runs stop when the screen is off | Battery settings again; only then consider `termux-wake-lock`. |

## 13. Updating later

```bash
cd ~/garmin-fitness-sync
git pull
.venv/bin/pip install -r requirements.txt
```

`.env`, `data/` and `logs/` are gitignored, so a pull never touches your
credentials or your snapshot.
