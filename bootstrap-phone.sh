#!/data/data/com.termux/files/usr/bin/bash
#
# One-shot Termux setup for the Garmin -> Notion sync.
#
# Run this INSIDE Termux (or via `adb shell run-as com.termux sh ...`) on a new
# phone. It installs everything and registers the hourly job. It does NOT move
# credentials -- those are copied separately, see PHONE-SETUP.md.
#
# Safe to re-run: every step is idempotent.
#
# Usage, from a laptop with the phone on USB:
#   adb push bootstrap-phone.sh /data/local/tmp/
#   adb shell run-as com.termux sh /data/local/tmp/bootstrap-phone.sh

set -u

export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
export LD_LIBRARY_PATH=$PREFIX/lib
export TMPDIR=$PREFIX/tmp
export LANG=en_US.UTF-8
export DEBIAN_FRONTEND=noninteractive

PROJECT="$HOME/garmin-fitness-sync"
LOGS="$HOME/setuplogs"
mkdir -p "$LOGS"

# --force-confdef/--force-confold: without these, dpkg stops on a config-file
# prompt and there is no terminal attached to answer it.
APTOPT="-y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold"

step() { printf '\n=== %s ===\n' "$1"; }

step "1/6 package lists"
apt-get update -y >"$LOGS/update.log" 2>&1 </dev/null
echo "exit=$?"

step "2/6 repairing any half-finished install"
# A previous interrupted run can leave dpkg mid-transaction; this is a no-op
# on a clean system.
dpkg --configure -a --force-confdef --force-confold >"$LOGS/repair.log" 2>&1 </dev/null
echo "exit=$?"

step "3/6 python, git, and the toolchain curl_cffi needs to build"
apt-get install $APTOPT python git binutils clang libffi termux-api \
    >"$LOGS/pkgs.log" 2>&1 </dev/null
echo "exit=$?"
python3 --version
git --version

step "4/6 python dependencies"
# curl_cffi has no Android wheel and must compile from source -- this is the
# slow step (a few minutes) and the one most likely to fail on a new Android
# or Python version. It DOES work; do not assume otherwise without trying.
python3 -m pip install --upgrade pip >"$LOGS/pip.log" 2>&1 </dev/null
python3 -m pip install curl_cffi garminconnect python-dotenv tzdata requests \
    >>"$LOGS/pip.log" 2>&1 </dev/null
echo "exit=$?"
python3 - <<'PY'
mods = ["curl_cffi", "garminconnect", "dotenv", "requests", "zoneinfo"]
bad = []
for m in mods:
    try:
        __import__(m)
    except Exception as exc:
        bad.append(f"{m}: {exc}")
print("imports OK" if not bad else "IMPORT FAILURES:\n  " + "\n  ".join(bad))
PY

step "5/6 project files"
if [ -d "$PROJECT" ]; then
    echo "project dir present: $PROJECT"
    ls -1 "$PROJECT" | head -20
else
    echo "MISSING: $PROJECT"
    echo "Push the source files first (see PHONE-SETUP.md) and re-run."
    exit 1
fi
chmod +x "$PROJECT/run_sync.sh"

step "6/6 hourly job"
# Android's minimum period is 15 minutes; 1 hour is the V1 target.
# battery-not-low=false: the job is a few seconds, so it should not be skipped
# just because the battery dipped.
termux-job-scheduler \
    --script "$PROJECT/run_sync.sh" \
    --job-id 1 \
    --period-ms 3600000 \
    --network any \
    --battery-not-low false 2>&1
echo
echo "--- pending jobs ---"
termux-job-scheduler --pending 2>&1

cat <<'DONE'

===========================================================
Termux side complete.

Still required, and NOT done by this script:
  * credentials: .env and ~/.garminconnect/garmin_tokens.json
  * battery exemption + standby bucket (adb, from the laptop)
  * phantom-process monitoring off (adb, from the laptop)
All three are in PHONE-SETUP.md.

Verify with:
  cd ~/garmin-fitness-sync && ./run_sync.sh
===========================================================
DONE
