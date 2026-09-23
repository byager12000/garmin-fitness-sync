# Setting up the sync on an Android phone

**This is the procedure that actually worked**, recorded on 2026-09-23 while
setting up a Galaxy S24 Ultra on Android 16. It is driven from the laptop over
USB, which is far less painful than typing commands on a phone keyboard.

If you are replacing a phone, this whole thing is about 15–20 minutes.

Read [TERMUX-SETUP.md](TERMUX-SETUP.md) only if you want the manual,
type-it-yourself version. This file supersedes it.

---

## What you actually need

- The phone, and a **USB data cable** (charge-only cables look identical and
  silently do nothing — this cost us an hour)
- `adb` on the laptop: `winget install Google.PlatformTools`
- The Termux and Termux:API APKs from GitHub — **both from the same source**,
  because Termux plugins share an Android user ID and Android refuses to
  install them if the signatures differ

---

## 1. Phone: enable USB debugging

1. **Settings → About phone → Software information → tap "Build number" ×7**
2. **Settings → Developer options → USB debugging → on**
3. Plug in. Set USB mode to **Transferring files** (Samsung reverts to
   *Charging only* on every reconnect).
4. Tap **Allow** on the "Allow USB debugging?" prompt, ticking *Always allow*.

```bash
adb devices -l      # should list the phone as "device", not "unauthorized"
```

> **Gotcha we hit:** USB debugging silently switched itself off after a phone
> reboot. If the device stops appearing, check that toggle first — and if
> Windows can see the phone as a portable device but `adb` cannot, that is
> exactly this, not a cable fault.

## 2. Install Termux and Termux:API

**This is the step that fails confusingly.** Android's package verifier
(Play Protect) blocks both APKs with `INSTALL_FAILED_VERIFICATION_FAILURE`,
which the phone's own installer reports only as *"app not installed"* or
*"unknown error"*. Installing via `adb` is what reveals the real reason.

The verifier has to be turned off for the install, then turned back on:

```bash
adb shell settings put global verifier_verify_adb_installs 0
adb shell settings put global package_verifier_enable 0

adb install -r --bypass-low-target-sdk-block termux-app_*_arm64-v8a.apk
adb install -r --bypass-low-target-sdk-block termux-api-app_*.apk

# put it straight back
adb shell settings delete global verifier_verify_adb_installs
adb shell settings delete global package_verifier_enable
```

`--bypass-low-target-sdk-block` is needed because Termux's last release (2023)
targets an older Android API than Android 15+ accepts by default.

Then launch Termux once so it unpacks its bootstrap:

```bash
adb shell monkey -p com.termux -c android.intent.category.LAUNCHER 1
sleep 20
```

## 3. The `run-as` trick

Termux's GitHub builds are **debug** builds, which means `adb shell run-as`
works. That is what makes this whole procedure possible — it gives a shell as
the Termux user without needing SSH, a password, or anything typed on the
phone:

```bash
adb shell run-as com.termux sh /data/local/tmp/some-script.sh
```

Scripts must be staged in `/data/local/tmp` (world-readable) and **copied**
into Termux's home with `cp`, not `mv` — the Termux user can read that
directory but cannot unlink from it.

Always set the environment at the top of any such script:

```sh
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
export LD_LIBRARY_PATH=$PREFIX/lib
export TMPDIR=$PREFIX/tmp
```

`/tmp` does not exist in Termux — use `$TMPDIR` or `$HOME` for scratch files.

## 4. Push the code and run the bootstrap

The GitHub repo is private, so push the files rather than cloning:

```bash
adb shell mkdir -p /data/local/tmp/gfs
adb push sync_garmin.py garmin_client.py normalize.py storage.py \
         notion_client.py notion_page.py config.py runlock.py \
         run_sync.sh requirements.txt /data/local/tmp/gfs/
adb push bootstrap-phone.sh /data/local/tmp/
```

Copy them into place and run the bootstrap (installs packages, builds
`curl_cffi`, registers the hourly job):

```bash
adb shell run-as com.termux sh -c 'mkdir -p files/home/garmin-fitness-sync'
# then a small script that cp's each file, since globs do not expand through adb
adb shell run-as com.termux sh /data/local/tmp/bootstrap-phone.sh
```

> **`curl_cffi` does build on Termux.** Published guidance says Android is
> unsupported, and the wheel-only install genuinely fails — but the source
> build succeeds in a few minutes given `clang` and `libffi`. Do not reach for
> the `proot-distro` Debian workaround without trying it first.

## 5. Credentials — copy, never log in

**Do not log in to Garmin on the phone.** The token store is three opaque
strings (`di_token`, `di_refresh_token`, `di_client_id`) with no device
binding, so copying it from the laptop gives the phone an already-authenticated
session. That avoids the MFA prompt *and* Garmin's per-IP 429 throttle, which
only ever affects the login endpoints.

```bash
adb push %USERPROFILE%\.garminconnect\garmin_tokens.json /data/local/tmp/gfs/gt.json
adb push phone.env /data/local/tmp/gfs/dotenv
```

Then, inside Termux:

```sh
cp /data/local/tmp/gfs/dotenv  ~/garmin-fitness-sync/.env
cp /data/local/tmp/gfs/gt.json ~/.garminconnect/garmin_tokens.json
chmod 600 ~/garmin-fitness-sync/.env
chmod 700 ~/.garminconnect && chmod 600 ~/.garminconnect/garmin_tokens.json
```

Finally **scrub the staging area** — `/data/local/tmp` is world-readable:

```bash
adb shell rm -rf /data/local/tmp/gfs
```

The phone's `.env` should contain only `NOTION_TOKEN`, `NOTION_PAGE_TITLE` and
`ACTIVITY_LOOKBACK_DAYS`. **Leave the Garmin email and password out entirely** —
the token authenticates, so no Garmin password needs to exist on the phone.

## 6. Stop Android throttling it

Three settings, all from the laptop. Skipping these is why Termux jobs
"mysteriously stop working after a day or two".

```bash
# exempt from battery optimisation
adb shell dumpsys deviceidle whitelist +com.termux
adb shell dumpsys deviceidle whitelist +com.termux.api

# Termux:API has no UI, so Android parks it in the "never used" standby
# bucket (50) and defers its jobs almost indefinitely. Promote both.
adb shell am set-standby-bucket com.termux active
adb shell am set-standby-bucket com.termux.api active

# stop Android killing Termux's child processes (the "phantom process" limit)
adb shell settings put global settings_enable_monitor_phantom_procs false
adb shell device_config put activity_manager max_phantom_processes 2147483647
```

Verify:

```bash
adb shell dumpsys deviceidle whitelist | grep termux
adb shell am get-standby-bucket com.termux.api   # want a low number, not 50
```

## 7. Verify without waiting an hour

Force the scheduled job to fire:

```bash
adb shell cmd jobscheduler run -f com.termux.api 1
```

Then check it actually ran:

```bash
adb shell run-as com.termux cat files/home/garmin-fitness-sync/logs/run_sync.log
adb shell run-as com.termux tail -6 files/home/garmin-fitness-sync/logs/sync.log
```

A new line in `run_sync.log` proves the **scheduler** invoked it, not just that
the script works. Then confirm `Last attempt` on the Notion page is seconds old.

Inspect the registered job with:

```bash
adb shell dumpsys jobscheduler | grep -A12 "com.termux.api/.apis.JobSchedulerAPI"
```

You want `PERIODIC: interval=+1h0m0s0ms`.

## 8. Reboot survival — Termux:Boot is REQUIRED

**Periodic jobs do not survive a reboot.** Confirmed empirically on Android 16:
after the first restart, `termux-job-scheduler --pending` came back empty and
the sync had silently stopped. Do not skip this step, and do not assume the job
persisted — check it.

Install Termux:Boot the same way as the other two APKs (§2, with the verifier
temporarily off), then launch it once so Android arms it:

```bash
adb shell monkey -p com.termux.boot -c android.intent.category.LAUNCHER 1
adb shell dumpsys deviceidle whitelist +com.termux.boot
```

`bootstrap-phone.sh` writes the hook that does the re-registration, at
`~/.termux/boot/00-garmin-sync.sh`. It logs to `logs/boot.log`, so after a
restart you can confirm it fired:

```bash
adb shell run-as com.termux tail -4 files/home/garmin-fitness-sync/logs/boot.log
```

You can test the hook without rebooting by running it directly:

```bash
adb shell run-as com.termux sh files/home/.termux/boot/00-garmin-sync.sh
```

That only proves the script works, not that Termux:Boot triggers it — for that
you have to actually reboot and check `--pending` afterwards.

## 9. Afterwards

- **Turn USB debugging back off** in Developer options. Note it also seems to
  switch itself off on its own after a reboot, which presents convincingly as
  a dead USB cable.
- Let it run a day or two. The health check is simply that **Last updated** on
  the Notion page is never more than about an hour old.

## Timezone

The sync follows the **phone's** timezone, which is correct and deliberate —
it means a travel day follows you. Note that the phone and the laptop can
disagree (ours did: phone on `America/Los_Angeles`, laptop on Eastern), and
whichever device runs the sync decides what "today" means. Once the phone is
the only thing syncing, this is a non-issue.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `adb` shows nothing, but Windows sees the phone as a portable device | USB debugging is off — it can switch itself off after a reboot |
| "App not installed" / "unknown error" on the phone | The package verifier. Install via adb to see the real error |
| `INSTALL_FAILED_VERIFICATION_FAILURE` | Verifier again — step 2 |
| Termux plugin refuses to install | Signature mismatch — every Termux app must come from the same source |
| `pip install curl_cffi` fails with `--only-binary` | Expected; there is no Android wheel. Let it build from source |
| dpkg stops with "end of file on stdin at conffile prompt" | Missing `--force-confdef --force-confold` |
| `can't create /tmp/...: Permission denied` | Termux has no `/tmp`; use `$TMPDIR` or `$HOME` |
| `mv: Permission denied` from `/data/local/tmp` | Use `cp`; Termux cannot unlink there |
| Job registered but never fires | Standby bucket 50, or battery optimisation — step 6 |
| Sync silently stops after a reboot | Periodic jobs do NOT persist. Termux:Boot + the boot hook — step 8 |
| Syncs stop after a day or two | Battery optimisation, or the phantom-process killer — step 6 |
