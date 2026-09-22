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

from config import Config, timezone_label
from garmin_client import GarminAdapter, GarminAuthRequired
from normalize import normalize

# Exit codes. Phase 4 finalizes these; they are here so the program already
# says something meaningful to a scheduler.
EXIT_CODES = {
    "OK": 0,
    "FAILED": 1,
    "AUTH_REQUIRED": 2,
    "GARMIN_UNAVAILABLE": 3,
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

    if sync["unavailable_endpoints"] or sync["empty_endpoints"]:
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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    cfg = Config.from_env()
    if args.days is not None:
        cfg.lookback_days = max(0, args.days)

    tz = cfg.timezone
    attempted_at = datetime.now(tz)
    today = attempted_at.date()
    window_start = today - timedelta(days=cfg.lookback_days)

    adapter = GarminAdapter(cfg)
    try:
        adapter.connect(prompt_mfa=prompt_mfa)
    except GarminAuthRequired as exc:
        print(f"AUTH_REQUIRED: {exc}", file=sys.stderr)
        return EXIT_CODES["AUTH_REQUIRED"]
    except Exception as exc:  # unofficial API: surface, do not crash silently
        # The MFA-without-a-terminal case arrives wrapped by the library, so
        # match on the cause chain as well as the exception itself.
        cause: BaseException | None = exc
        while cause is not None:
            if isinstance(cause, MFANotPossible):
                print(f"AUTH_REQUIRED: {cause}", file=sys.stderr)
                return EXIT_CODES["AUTH_REQUIRED"]
            cause = cause.__cause__ or cause.__context__
        if "EOF when reading a line" in str(exc):
            print(
                "AUTH_REQUIRED: Garmin asked for a multi-factor code but no "
                "terminal was available to read it. Run this by hand in a "
                "terminal once to complete MFA.",
                file=sys.stderr,
            )
            return EXIT_CODES["AUTH_REQUIRED"]
        if "429" in str(exc) or "rate" in str(exc).lower():
            print(
                f"AUTH_REQUIRED: Garmin is rate-limiting this IP (429). Wait "
                f"before retrying -- do not retry in a loop. Detail: {exc}",
                file=sys.stderr,
            )
            return EXIT_CODES["AUTH_REQUIRED"]
        print(f"FAILED: unexpected login error: {exc}", file=sys.stderr)
        return EXIT_CODES["FAILED"]

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

    if not args.json:
        print(render_summary(payload))
    if not args.summary:
        print(json.dumps(payload, indent=2, default=str))

    return EXIT_CODES.get(payload["sync"]["status"], EXIT_CODES["FAILED"])


if __name__ == "__main__":
    raise SystemExit(main())
