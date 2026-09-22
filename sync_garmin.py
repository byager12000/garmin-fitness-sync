"""Phase 1 entry point: log in to Garmin, fetch, normalize, print.

Read-only. This program never writes anything back to Garmin, and in Phase 1 it
writes nothing to disk except the Garmin token store the library manages itself.

Usage:
    uv run python sync_garmin.py              # summary + normalized JSON
    uv run python sync_garmin.py --summary    # human summary only
    uv run python sync_garmin.py --json       # normalized JSON only
    uv run python sync_garmin.py --days 14    # widen the activity window
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from typing import Any

import storage
from config import Config, timezone_label
from garmin_client import GarminAdapter, GarminAuthRequired
from normalize import normalize
from notion_client import NotionAdapter, NotionError, NotionPageNotFound
from notion_page import build_blocks
from runlock import LockHeld, RunLock

# Exit codes. Phase 4 finalizes these; they are here so the program already
# says something meaningful to a scheduler.
EXIT_CODES = {
    "OK": 0,
    "FAILED": 1,
    "AUTH_REQUIRED": 2,
    "GARMIN_UNAVAILABLE": 3,
    "NOTION_UNAVAILABLE": 4,
    "PARTIAL": 10,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Garmin Connect data and print a normalized snapshot."
    )
    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--summary", action="store_true", help="print only the human summary"
    )
    output.add_argument(
        "--json", action="store_true", help="print only the normalized JSON"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="days of activity history to fetch (default 7)",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="show debug logging on stderr"
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="do not touch data/latest.json (useful when debugging)",
    )
    parser.add_argument(
        "--no-notion",
        action="store_true",
        help="skip the Notion update (fetch and save locally only)",
    )
    parser.add_argument(
        "--ignore-lock",
        action="store_true",
        help="run even if another sync holds the lock (debugging only)",
    )
    return parser.parse_args(argv)


def _fmt(value: Any, suffix: str = "") -> str:
    """Render a value for the console, making missing data obvious."""
    if value is None:
        return "-"
    if isinstance(value, float):
        value = int(value) if value.is_integer() else round(value, 2)
    return f"{value}{suffix}"


def _row(label: str, value: Any, suffix: str = "") -> str:
    return f"  {label:<24} {_fmt(value, suffix)}"


def render_summary(payload: dict[str, Any]) -> str:
    sync = payload["sync"]
    today = payload["today"]
    sleep = payload["sleep"]
    recovery = payload["recovery"]
    body = payload["body"]
    seven = payload["seven_day"]

    lines: list[str] = []
    lines.append("=" * 62)
    lines.append(f"  GARMIN SNAPSHOT  {today['date']}  ({sync['timezone']})")
    lines.append(f"  status: {sync['status']}   attempt: {sync['last_attempt']}")
    lines.append("=" * 62)

    lines.append("")
    lines.append("TODAY")
    lines.append(_row("Steps", today["steps"]))
    lines.append(_row("Step goal", today["step_goal"]))
    lines.append(_row("Distance", today["distance_miles"], " mi"))
    lines.append(_row("Active calories", today["active_calories"], " kcal"))
    lines.append(_row("Resting calories", today["resting_calories"], " kcal"))
    lines.append(_row("Total calories", today["total_calories"], " kcal"))
    lines.append(_row("Intensity minutes", today["intensity_minutes"]))
    lines.append(_row("Floors ascended", today["floors_ascended"]))
    lines.append(_row("Resting HR", today["resting_hr_bpm"], " bpm"))
    lines.append(_row("Stress (avg)", today["stress_avg"]))
    lines.append(_row("Body Battery (now)", today["body_battery_current"]))
    lines.append(
        _row(
            "Body Battery hi/lo",
            f"{_fmt(today['body_battery_high'])} / {_fmt(today['body_battery_low'])}",
        )
    )

    lines.append("")
    lines.append("LAST NIGHT")
    lines.append(_row("Sleep duration", sleep["duration_hours"], " h"))
    lines.append(_row("Sleep score", sleep["score"] or sleep["score_label"]))
    stages = sleep["stages_hours"]
    lines.append(
        _row(
            "Stages (D/L/R/A)",
            " / ".join(
                _fmt(stages[k]) for k in ("deep", "light", "rem", "awake")
            ),
        )
    )
    lines.append(_row("HRV (overnight)", sleep["hrv_ms"], " ms"))
    lines.append(_row("HRV status", sleep["hrv_status"]))

    lines.append("")
    lines.append("RECOVERY")
    lines.append(_row("Training readiness", recovery["training_readiness"]))
    lines.append(_row("Readiness level", recovery["training_readiness_level"]))
    lines.append(_row("Recovery time", recovery["recovery_hours"], " h"))
    lines.append(_row("Training status", recovery["training_status"]))
    lines.append(_row("VO2 max", recovery["vo2_max"]))
    lines.append(_row("Fitness age", recovery["fitness_age"]))

    lines.append("")
    lines.append("BODY")
    lines.append(_row("Weight", body["weight_lb"], " lb"))
    lines.append(_row("BMI", body["bmi"]))
    lines.append(_row("Body fat", body["body_fat_percent"], " %"))

    lines.append("")
    activities = payload["recent_activities"]
    lines.append(f"RECENT ACTIVITIES ({len(activities)} in {seven['window_days']} days)")
    if not activities:
        lines.append("  (none)")
    for act in activities:
        when = (act["start"] or "")[:16].replace("T", " ")
        bits = [
            f"{when:<16}",
            f"{(act['type'] or 'unknown'):<18}",
            f"{_fmt(act['duration_minutes']):>6} min",
            f"{_fmt(act['distance_miles']):>6} mi",
            f"{_fmt(act['calories']):>5} kcal",
        ]
        if act["avg_pace"]:
            bits.append(f"{act['avg_pace']:>10}")
        elif act["avg_speed_mph"]:
            bits.append(f"{_fmt(act['avg_speed_mph']):>6} mph")
        if act["avg_hr_bpm"]:
            bits.append(f"{_fmt(act['avg_hr_bpm']):>4} bpm")
        lines.append("  " + "  ".join(bits))
        if act["name"]:
            lines.append(f"    {act['name']}")

    lines.append("")
    lines.append(f"LAST {seven['window_days']} DAYS")
    lines.append(_row("Workouts", seven["workouts"]))
    lines.append(_row("Activity minutes", seven["activity_minutes"]))
    lines.append(_row("Activity calories", seven["activity_calories"], " kcal"))
    lines.append(_row("Running", seven["running_miles"], " mi"))
    lines.append(_row("Cycling", seven["cycling_miles"], " mi"))
    lines.append(_row("Walking / hiking", seven["walking_miles"], " mi"))

    stale = sync.get("stale_sections") or []
    if sync["unavailable_endpoints"] or sync["empty_endpoints"] or stale:
        lines.append("")
        lines.append("DATA AVAILABILITY")
        if sync["unavailable_endpoints"]:
            lines.append(
                "  failed:  " + ", ".join(sync["unavailable_endpoints"])
            )
        if sync["empty_endpoints"]:
            lines.append(
                "  empty:   " + ", ".join(sync["empty_endpoints"])
            )
        if stale:
            lines.append("  stale:   " + ", ".join(stale))
            lines.append(
                "  (stale = carried over from the last good sync, NOT fresh)"
            )
        lines.append(
            "  (empty means Garmin answered but had nothing for this account/day)"
        )

    lines.append("")
    return "\n".join(lines)


class MFANotPossible(Exception):
    """Garmin wants an MFA code but there is no one at the keyboard."""


def prompt_mfa() -> str:
    """Interactive MFA prompt for the very first login on a machine.

    When stdin is not a terminal -- a scheduled run, a pipe, an automation --
    there is nobody to type the code, so say so plainly instead of dying with
    a bare `EOF when reading a line` from input().
    """
    no_terminal = MFANotPossible(
        "Garmin asked for a multi-factor code, but this process has no "
        "terminal to read it from. Run the sync by hand in a terminal once to "
        "complete MFA; the cached token is then reused automatically."
    )
    # isatty() is not trustworthy -- some harnesses report a tty while stdin is
    # really /dev/null, so the EOFError below is the reliable signal.
    if not sys.stdin.isatty():
        raise no_terminal
    print(
        "\nGarmin is asking for a multi-factor code "
        "(check your email or authenticator).",
        file=sys.stderr,
    )
    try:
        return input("MFA code: ").strip()
    except EOFError:
        raise no_terminal from None


def classify_login_failure(exc: BaseException) -> tuple[str, str]:
    """Turn a login exception into (status, human message).

    The interesting cases arrive wrapped by the library, so the cause chain is
    walked rather than only inspecting the outermost exception.
    """
    if isinstance(exc, GarminAuthRequired):
        return "AUTH_REQUIRED", str(exc)

    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, MFANotPossible):
            return "AUTH_REQUIRED", str(cause)
        cause = cause.__cause__ or cause.__context__

    text = str(exc)
    if "EOF when reading a line" in text:
        return (
            "AUTH_REQUIRED",
            "Garmin asked for a multi-factor code but no terminal was "
            "available to read it. Run this by hand in a terminal once to "
            "complete MFA.",
        )
    if "429" in text or "rate limit" in text.lower():
        return (
            "AUTH_REQUIRED",
            f"Garmin is rate-limiting this IP (429). Wait before retrying -- "
            f"do not retry in a loop. Detail: {text}",
        )
    return "FAILED", f"unexpected login error: {text}"


def publish_to_notion(cfg: Config, payload: dict[str, Any]) -> str | None:
    """Update the Fitness Live page. Returns an error message, or None on success.

    A Notion failure never invalidates the Garmin data: the snapshot is already
    saved locally by the time this runs, so the caller reports
    NOTION_UNAVAILABLE and the next run simply republishes.
    """
    log = logging.getLogger("sync")
    try:
        adapter = NotionAdapter(
            cfg.notion_token or "",
            page_id=cfg.notion_page_id,
            page_title=cfg.notion_page_title,
        )
        page_id = adapter.resolve_page_id()
        adapter.replace_managed_section(page_id, build_blocks(payload))
    except NotionPageNotFound as exc:
        log.error("notion page not found: %s", exc)
        return str(exc)
    except NotionError as exc:
        log.error("notion update failed: %s", exc)
        return str(exc)
    except Exception as exc:  # never let Notion take down a good Garmin run
        log.exception("unexpected Notion failure")
        return f"unexpected Notion failure: {exc}"

    log.info("notion page updated")
    return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    storage.setup_logging(verbose=args.verbose)
    log = logging.getLogger("sync")

    if args.ignore_lock:
        log.warning("running without the single-instance lock (--ignore-lock)")
        return run(args)

    lock = RunLock()
    try:
        lock.acquire()
    except LockHeld as exc:
        # Overlapping runs are a normal condition for an hourly scheduler, not
        # a failure, so this exits 0 and says why rather than alarming Tasker.
        log.info("skipped: %s", exc)
        print(f"SKIPPED: {exc}", file=sys.stderr)
        return EXIT_CODES["OK"]

    try:
        return run(args)
    finally:
        lock.release()


def run(args: argparse.Namespace) -> int:
    log = logging.getLogger("sync")
    cfg = Config.from_env()
    if args.days is not None:
        cfg.lookback_days = max(0, args.days)

    tz = cfg.timezone
    attempted_at = datetime.now(tz)
    today = attempted_at.date()
    window_start = today - timedelta(days=cfg.lookback_days)

    previous = storage.load_previous()
    log.info(
        "run start: date=%s window=%sd tz=%s previous_snapshot=%s",
        today,
        cfg.lookback_days,
        timezone_label(tz),
        "yes" if previous else "no",
    )

    adapter = GarminAdapter(cfg)
    try:
        adapter.connect(prompt_mfa=prompt_mfa)
    except Exception as exc:
        status, message = classify_login_failure(exc)
        print(f"{status}: {message}", file=sys.stderr)
        log.error("login failed (%s): %s", status, message)
        # A failed login must never erase working data: keep every previous
        # section and update only the sync block.
        snapshot = storage.failure_snapshot(
            previous, status=status, attempted_at=attempted_at, detail=message
        )
        if snapshot is not None:
            if not args.no_write:
                storage.write_atomic(snapshot)
            # Still tell Notion the sync is failing, without erasing the good
            # data already on the page -- a silently stale page is worse than
            # one that says so.
            if cfg.notion_configured and not args.no_notion:
                publish_to_notion(cfg, snapshot)
        return EXIT_CODES[status]

    if not args.json:
        source = "stored tokens" if adapter.used_stored_tokens else "fresh login"
        print(
            f"Authenticated via {source} "
            f"(token store: {cfg.tokenstore_path})",
            file=sys.stderr,
        )

    raw, results = adapter.fetch_raw(today, window_start)
    payload = normalize(
        raw,
        results,
        today=today,
        tz=tz,
        lookback_days=cfg.lookback_days,
        attempted_at=attempted_at,
    )
    payload = storage.finalize(payload, previous, results)

    sync = payload["sync"]
    log.info(
        "run end: status=%s failed=%s empty=%s stale=%s activities=%d",
        sync["status"],
        sync["unavailable_endpoints"] or "-",
        sync["empty_endpoints"] or "-",
        sync["stale_sections"] or "-",
        len(payload["recent_activities"]),
    )

    # Save locally BEFORE publishing: a Notion outage must never cost us the
    # Garmin data we just fetched.
    if not args.no_write:
        storage.write_atomic(payload)

    notion_error: str | None = None
    notion_skipped: str | None = None
    if args.no_notion:
        notion_skipped = "skipped (--no-notion)"
    elif not cfg.notion_configured:
        notion_skipped = "skipped (NOTION_TOKEN not set)"
    else:
        notion_error = publish_to_notion(cfg, payload)

    if not args.json:
        print(render_summary(payload))
        if not args.no_write:
            print(f"  Snapshot written to {storage.SNAPSHOT_PATH}")
        if notion_skipped:
            print(f"  Notion             {notion_skipped}")
        elif notion_error:
            print(f"  Notion             FAILED - {notion_error}")
        else:
            print(f"  Notion page        updated ({cfg.notion_page_title})")
        print(f"  Log appended to    {storage.LOG_PATH}")
        print()
    if not args.summary:
        print(json.dumps(payload, indent=2, default=str))

    if notion_error:
        # The Garmin half succeeded and is safely on disk; only the publish
        # failed, so report that distinctly rather than as a Garmin problem.
        return EXIT_CODES["NOTION_UNAVAILABLE"]
    return EXIT_CODES.get(sync["status"], EXIT_CODES["FAILED"])


if __name__ == "__main__":
    raise SystemExit(main())
