#!/data/data/com.termux/files/usr/bin/bash
#
# Single launch entry point for the Garmin -> Notion sync (Phase 5).
#
# Runs one sync and exits. There is no loop in here: the Android scheduler
# starts the process, the process finishes, Android reclaims it. A resident
# Python process would be killed by Doze anyway, and would drain the battery
# while it waited to be killed.
#
# Safe to run by hand too -- overlapping runs are handled by the lock inside
# sync_garmin.py, so a manual run during a scheduled one simply exits 0.
#
# Usage:
#   ./run_sync.sh                # normal hourly run
#   ./run_sync.sh --summary      # any sync_garmin.py flag passes through
#
# The shebang above is Termux's bash. On a normal Linux box (or proot-distro)
# use:  bash run_sync.sh

set -uo pipefail

# Resolve this script's own directory, so it works from any cwd -- Tasker
# launches with an unpredictable working directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || {
    echo "run_sync: cannot cd to $SCRIPT_DIR" >&2
    exit 1
}

# Prefer the project venv. The Scripts/ variant is the Windows layout, kept so
# this exact launcher can be smoke-tested on the laptop (Git Bash) before it is
# trusted on the phone; on Termux the bin/ branch is the one that matches.
if [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
elif [ -x ".venv/Scripts/python.exe" ]; then
    PYTHON=".venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
else
    echo "run_sync: no python found. Create the venv first:" >&2
    echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

# Keep a small launcher log separate from the app log, so a failure that
# happens *before* Python starts is still visible.
mkdir -p logs
LAUNCH_LOG="logs/run_sync.log"

# Cap the launcher log. The app's own log rotates via Python; this one is
# tiny, but an hourly job runs ~8760 times a year, so it still needs a bound.
if [ -f "$LAUNCH_LOG" ] && [ "$(wc -c < "$LAUNCH_LOG")" -gt 262144 ]; then
    mv -f "$LAUNCH_LOG" "$LAUNCH_LOG.1"
fi

STARTED="$(date -Iseconds)"
"$PYTHON" sync_garmin.py --summary "$@"
STATUS=$?

case "$STATUS" in
    0)  MEANING="OK (or skipped: another run held the lock)" ;;
    1)  MEANING="FAILED" ;;
    2)  MEANING="AUTH_REQUIRED - needs an interactive login" ;;
    3)  MEANING="GARMIN_UNAVAILABLE" ;;
    4)  MEANING="NOTION_UNAVAILABLE - Garmin data was still saved locally" ;;
    10) MEANING="PARTIAL - some endpoints failed" ;;
    *)  MEANING="unknown" ;;
esac

echo "$STARTED exit=$STATUS $MEANING" >> "$LAUNCH_LOG"

# Tasker reads this exit code. 0 and 10 are both "the sync did its job";
# anything else is worth surfacing.
exit "$STATUS"
