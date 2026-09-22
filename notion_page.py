"""Builds the Notion page body from a normalized snapshot (Phase 3).

Optimised for machine retrieval first, human readability second, per the spec.
The headings are deliberately fixed and stable -- ChatGPT retrieval depends on
them not moving around between syncs:

    Sync status / Today / Sleep and recovery / Today's activities /
    Last 7 days / Machine-readable snapshot

Anything Garmin did not provide renders as `-`, and carried-over data is
labelled stale rather than quietly presented as current.
"""

from __future__ import annotations

import json
from typing import Any

from notion_client import (
    bullet,
    callout,
    code_block,
    heading,
    paragraph,
    table_rows,
)

STATUS_ICON = {
    "OK": "✅",
    "PARTIAL": "⚠️",
    "AUTH_REQUIRED": "🔑",
    "GARMIN_UNAVAILABLE": "🚫",
    "NOTION_UNAVAILABLE": "🚫",
    "FAILED": "❌",
}


def _fmt(value: Any, suffix: str = "") -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        value = int(value) if value.is_integer() else round(value, 2)
    return f"{value}{suffix}"


def _activity_line(act: dict[str, Any]) -> str:
    when = (act.get("start") or "")[:16].replace("T", " ")
    bits = [
        when or "-",
        act.get("type") or "unknown",
        _fmt(act.get("duration_minutes"), " min"),
        _fmt(act.get("distance_miles"), " mi"),
        _fmt(act.get("calories"), " kcal"),
    ]
    if act.get("avg_pace"):
        bits.append(str(act["avg_pace"]))
    elif act.get("avg_speed_mph"):
        bits.append(_fmt(act["avg_speed_mph"], " mph"))
    if act.get("avg_hr_bpm"):
        bits.append(_fmt(act["avg_hr_bpm"], " bpm avg"))
    line = " · ".join(bits)
    name = act.get("name")
    return f"{line} — {name}" if name else line


def build_blocks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    sync = payload.get("sync", {})
    today = payload.get("today", {})
    sleep = payload.get("sleep", {})
    recovery = payload.get("recovery", {})
    body = payload.get("body", {})
    seven = payload.get("seven_day", {})
    activities = payload.get("recent_activities", []) or []

    status = sync.get("status", "UNKNOWN")
    stale = sync.get("stale_sections") or []
    blocks: list[dict[str, Any]] = []

    # -- Sync status ---------------------------------------------------
    blocks.append(heading("Sync status"))
    icon = STATUS_ICON.get(status, "❔")
    blocks.append(
        callout(
            f"Status: {status}. Data date {today.get('date') or '-'}. "
            f"Last success {sync.get('last_success') or 'never'}. "
            f"Last attempt {sync.get('last_attempt') or '-'}.",
            emoji=icon,
        )
    )
    if status != "OK":
        warning = {
            "PARTIAL": "Some Garmin endpoints failed this run. Sections marked "
            "stale below are carried over from the last good sync.",
            "AUTH_REQUIRED": "Garmin authentication failed. Everything below is "
            "from the last successful sync and may be out of date.",
            "GARMIN_UNAVAILABLE": "Garmin could not be reached. Everything below "
            "is from the last successful sync and may be out of date.",
            "FAILED": "The sync failed unexpectedly. Data below may be out of date.",
        }.get(status)
        if warning:
            blocks.append(callout(warning, emoji="⚠️"))
    if stale:
        blocks.append(
            callout(
                "Stale (carried over, NOT fresh): " + ", ".join(stale),
                emoji="🕰️",
            )
        )
    if sync.get("last_error"):
        blocks.append(paragraph(f"Last error: {sync['last_error']}"))

    # -- Today ---------------------------------------------------------
    blocks.append(heading("Today"))
    blocks.extend(
        table_rows(
            [
                ("Steps", _fmt(today.get("steps"))),
                ("Step goal", _fmt(today.get("step_goal"))),
                ("Distance", _fmt(today.get("distance_miles"), " mi")),
                ("Active calories", _fmt(today.get("active_calories"), " kcal")),
                ("Resting calories", _fmt(today.get("resting_calories"), " kcal")),
                ("Total calories", _fmt(today.get("total_calories"), " kcal")),
                ("Intensity minutes", _fmt(today.get("intensity_minutes"))),
                ("Floors ascended", _fmt(today.get("floors_ascended"))),
                ("Resting HR", _fmt(today.get("resting_hr_bpm"), " bpm")),
                ("Stress (avg)", _fmt(today.get("stress_avg"))),
                (
                    "Body Battery (now / high / low)",
                    f"{_fmt(today.get('body_battery_current'))} / "
                    f"{_fmt(today.get('body_battery_high'))} / "
                    f"{_fmt(today.get('body_battery_low'))}",
                ),
            ]
        )
    )

    # -- Sleep and recovery --------------------------------------------
    blocks.append(heading("Sleep and recovery"))
    stages = sleep.get("stages_hours") or {}
    blocks.extend(
        table_rows(
            [
                ("Sleep duration", _fmt(sleep.get("duration_hours"), " h")),
                ("Sleep score", _fmt(sleep.get("score") or sleep.get("score_label"))),
                (
                    "Sleep stages (deep / light / REM / awake)",
                    " / ".join(
                        _fmt(stages.get(k)) for k in ("deep", "light", "rem", "awake")
                    ),
                ),
                ("Overnight HRV", _fmt(sleep.get("hrv_ms"), " ms")),
                ("HRV status", _fmt(sleep.get("hrv_status"))),
                ("Training readiness", _fmt(recovery.get("training_readiness"))),
                ("Readiness level", _fmt(recovery.get("training_readiness_level"))),
                ("Recovery time remaining", _fmt(recovery.get("recovery_hours"), " h")),
                ("Training status", _fmt(recovery.get("training_status"))),
                ("Acute load", _fmt(recovery.get("acute_load"))),
                ("VO2 max", _fmt(recovery.get("vo2_max"))),
                ("Weight", _fmt(body.get("weight_lb"), " lb")),
            ]
        )
    )

    # -- Today's activities --------------------------------------------
    blocks.append(heading("Today's activities"))
    todays_date = today.get("date")
    todays = [a for a in activities if a.get("local_date") == todays_date]
    if todays:
        blocks.extend(bullet(_activity_line(a)) for a in todays)
    else:
        blocks.append(paragraph("No activities recorded today."))

    # -- Last 7 days ----------------------------------------------------
    window = seven.get("window_days", 7)
    blocks.append(heading(f"Last {window} days"))
    blocks.extend(
        table_rows(
            [
                ("Workouts", _fmt(seven.get("workouts"))),
                ("Activity minutes", _fmt(seven.get("activity_minutes"))),
                ("Activity calories", _fmt(seven.get("activity_calories"), " kcal")),
                ("Running", _fmt(seven.get("running_miles"), " mi")),
                ("Cycling", _fmt(seven.get("cycling_miles"), " mi")),
                ("Walking / hiking", _fmt(seven.get("walking_miles"), " mi")),
            ]
        )
    )
    earlier = [a for a in activities if a.get("local_date") != todays_date]
    if earlier:
        blocks.append(paragraph("Recent activities:"))
        blocks.extend(bullet(_activity_line(a)) for a in earlier)

    # -- Machine-readable snapshot --------------------------------------
    blocks.append(heading("Machine-readable snapshot"))
    blocks.append(
        paragraph(
            "Full normalized payload. Units: miles, min/mile, pounds, feet. "
            "Missing values are null, never zero."
        )
    )
    blocks.append(code_block(json.dumps(payload, indent=1, default=str)))
    return blocks
