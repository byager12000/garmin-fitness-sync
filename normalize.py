"""Raw Garmin payloads -> stable normalized schema (version 1).

This is the contract the Notion writer (Phase 3) and ChatGPT will depend on, so
it deliberately does not mirror Garmin's field names. Rules:

* Every value is optional. Anything missing normalizes to null, never to zero,
  never to an invented substitute.
* Garmin's field names vary by watch, account and endpoint, so values are read
  through `pick()` across the known aliases rather than one hard-coded key.
* Units are converted once, here, to the US-friendly presentation Ben wants:
  miles, min/mile, pounds, feet.
"""

from __future__ import annotations

from datetime import date, datetime, tzinfo
from typing import Any

from config import SCHEMA_VERSION, timezone_label

METERS_PER_MILE = 1609.344
FEET_PER_METER = 3.280839895
GRAMS_PER_POUND = 453.59237

# ------------------------------------------------------------------ helpers


def pick(source: Any, *keys: str) -> Any | None:
    """First non-null value among `keys`, or None. Tolerates non-dict input."""
    if not isinstance(source, dict):
        return None
    for key in keys:
        value = source.get(key)
        if value is not None:
            return value
    return None


def dig(source: Any, *path: str) -> Any | None:
    """Walk a nested dict path, returning None at the first missing step."""
    current = source
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
        if current is None:
            return None
    return current


def first(source: Any) -> Any | None:
    """Garmin returns some endpoints as a single-item list, others as a dict."""
    if isinstance(source, list):
        return source[0] if source else None
    return source


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def meters_to_miles(value: Any, digits: int = 2) -> float | None:
    n = _num(value)
    return None if n is None else round(n / METERS_PER_MILE, digits)


def meters_to_feet(value: Any, digits: int = 0) -> float | None:
    n = _num(value)
    return None if n is None else round(n * FEET_PER_METER, digits)


def grams_to_pounds(value: Any, digits: int = 1) -> float | None:
    n = _num(value)
    return None if n is None else round(n / GRAMS_PER_POUND, digits)


def seconds_to_minutes(value: Any, digits: int = 1) -> float | None:
    n = _num(value)
    return None if n is None else round(n / 60.0, digits)


def seconds_to_hours(value: Any, digits: int = 2) -> float | None:
    n = _num(value)
    return None if n is None else round(n / 3600.0, digits)


def minutes_to_hours(value: Any, digits: int = 1) -> float | None:
    n = _num(value)
    return None if n is None else round(n / 60.0, digits)


def mps_to_pace(value: Any) -> str | None:
    """Metres/second -> 'MM:SS/mi'. Returns None for zero or missing speed."""
    n = _num(value)
    if not n or n <= 0:
        return None
    seconds_per_mile = METERS_PER_MILE / n
    if seconds_per_mile > 3600:  # slower than 60 min/mi is not a useful pace
        return None
    minutes, seconds = divmod(int(round(seconds_per_mile)), 60)
    return "{}:{:02d}/mi".format(minutes, seconds)


def mps_to_mph(value: Any, digits: int = 1) -> float | None:
    n = _num(value)
    if not n or n <= 0:
        return None
    return round(n * 3600.0 / METERS_PER_MILE, digits)


# Sports where min/mile is the meaningful unit. Everything else (cycling,
# swimming, rowing...) reports mph instead, because "3:45/mi" on a bike ride
# reads like a world record rather than a pleasant evening.
PACE_SPORTS = ("running", "walking", "hiking", "treadmill")


def _is_pace_sport(type_key: Any) -> bool:
    return isinstance(type_key, str) and any(s in type_key for s in PACE_SPORTS)


def _epoch_ms_to_iso(value: Any, tz: tzinfo) -> str | None:
    n = _num(value)
    if n is None:
        return None
    try:
        return datetime.fromtimestamp(n / 1000.0, tz).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _local_stamp_to_iso(value: Any, tz: tzinfo) -> str | None:
    """Garmin activity stamps look like '2026-09-22 07:05:00' in local time."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=tz).isoformat()
        except ValueError:
            continue
    return None


# -------------------------------------------------------------- sections


def _today_section(raw: dict[str, Any], today: date) -> dict[str, Any]:
    summary = raw.get("user_summary") or {}
    stress = raw.get("stress") or {}
    intensity = raw.get("intensity_minutes") or {}
    floors = raw.get("floors") or {}
    battery = first(raw.get("body_battery")) or {}
    rhr = raw.get("resting_hr") or {}

    moderate = _num(pick(summary, "moderateIntensityMinutes"))
    if moderate is None:
        moderate = _num(pick(intensity, "moderateIntensityMinutes", "moderateValue"))
    vigorous = _num(pick(summary, "vigorousIntensityMinutes"))
    if vigorous is None:
        vigorous = _num(pick(intensity, "vigorousIntensityMinutes", "vigorousValue"))

    intensity_total = None
    if moderate is not None or vigorous is not None:
        # Garmin counts vigorous minutes double toward the weekly goal.
        intensity_total = (moderate or 0) + 2 * (vigorous or 0)

    return {
        "date": today.isoformat(),
        "steps": pick(summary, "totalSteps"),
        "step_goal": pick(summary, "dailyStepGoal", "stepGoal"),
        "distance_miles": meters_to_miles(
            pick(summary, "totalDistanceMeters", "dailyDistanceMeters")
        ),
        "floors_ascended": pick(summary, "floorsAscended")
        or pick(floors, "floorsAscended"),
        "elevation_gain_feet": meters_to_feet(pick(summary, "floorsAscendedInMeters")),
        "active_calories": pick(summary, "activeKilocalories"),
        "resting_calories": pick(summary, "bmrKilocalories"),
        "total_calories": pick(summary, "totalKilocalories"),
        "intensity_minutes": intensity_total,
        "intensity_minutes_moderate": moderate,
        "intensity_minutes_vigorous": vigorous,
        "resting_hr_bpm": pick(summary, "restingHeartRate")
        or pick(rhr, "restingHeartRate", "value"),
        "avg_hr_bpm": pick(summary, "averageHeartRate"),
        "max_hr_bpm": pick(summary, "maxHeartRate"),
        "min_hr_bpm": pick(summary, "minHeartRate"),
        "stress_avg": pick(summary, "averageStressLevel")
        or pick(stress, "avgStressLevel"),
        "stress_max": pick(summary, "maxStressLevel") or pick(stress, "maxStressLevel"),
        "body_battery_current": pick(
            summary, "bodyBatteryMostRecentValue", "currentDayBodyBattery"
        )
        or pick(battery, "bodyBatteryMostRecentValue"),
        "body_battery_high": pick(summary, "bodyBatteryHighestValue")
        or pick(battery, "charged"),
        "body_battery_low": pick(summary, "bodyBatteryLowestValue")
        or pick(battery, "drained"),
        # Only populated if the account actually tracks hydration; never a
        # dependency, per the spec.
        "hydration_oz": None,
    }


def _sleep_section(raw: dict[str, Any], tz: tzinfo) -> dict[str, Any]:
    sleep = raw.get("sleep") or {}
    daily = pick(sleep, "dailySleepDTO") or {}
    hrv_summary = pick(raw.get("hrv") or {}, "hrvSummary") or {}

    score = dig(daily, "sleepScores", "overall", "value")
    label = pick(daily, "sleepQualityTypeName")

    return {
        "start": _epoch_ms_to_iso(
            pick(daily, "sleepStartTimestampGMT", "sleepStartTimestampLocal"), tz
        ),
        "end": _epoch_ms_to_iso(
            pick(daily, "sleepEndTimestampGMT", "sleepEndTimestampLocal"), tz
        ),
        "duration_hours": seconds_to_hours(pick(daily, "sleepTimeSeconds")),
        "score": score if isinstance(score, (int, float)) else None,
        "score_label": label if isinstance(label, str) else None,
        "stages_hours": {
            "deep": seconds_to_hours(pick(daily, "deepSleepSeconds")),
            "light": seconds_to_hours(pick(daily, "lightSleepSeconds")),
            "rem": seconds_to_hours(pick(daily, "remSleepSeconds")),
            "awake": seconds_to_hours(pick(daily, "awakeSleepSeconds")),
        },
        "hrv_ms": pick(hrv_summary, "lastNightAvg"),
        "hrv_status": pick(hrv_summary, "status"),
        "hrv_seven_day_avg_ms": pick(hrv_summary, "weeklyAvg"),
    }


def _latest_readiness(entries: Any) -> dict[str, Any]:
    """Garmin returns several readiness snapshots per day; take the newest.

    Ordering is not guaranteed, so sort on the local timestamp rather than
    trusting entry [0].
    """
    if isinstance(entries, dict):
        return entries
    if not isinstance(entries, list) or not entries:
        return {}
    usable = [e for e in entries if isinstance(e, dict)]
    if not usable:
        return {}
    return max(
        usable,
        key=lambda e: str(pick(e, "timestampLocal", "timestamp") or ""),
    )


def _recovery_section(raw: dict[str, Any]) -> dict[str, Any]:
    readiness = _latest_readiness(raw.get("training_readiness"))
    status = raw.get("training_status") or {}
    max_metrics = first(raw.get("max_metrics")) or {}

    vo2 = dig(max_metrics, "generic", "vo2MaxPreciseValue")
    if vo2 is None:
        vo2 = dig(max_metrics, "generic", "vo2MaxValue")
    fitness_age = dig(max_metrics, "generic", "fitnessAge") or pick(
        max_metrics, "fitnessAge"
    )

    training_status_label = None
    load_focus = None
    # The device-keyed block normally sits under mostRecentTrainingStatus; some
    # accounts/versions expose it at the top level instead. Try both.
    latest = dig(status, "mostRecentTrainingStatus", "latestTrainingStatusData") or pick(
        status, "latestTrainingStatusData"
    )
    if isinstance(latest, dict) and latest:
        # Keyed by device id; take whichever device reported.
        device_entry = next(iter(latest.values()), None)
        training_status_label = pick(
            device_entry, "trainingStatusFeedbackPhrase", "trainingStatus"
        )
        load_focus = pick(device_entry, "trainingBalanceFeedbackPhrase")
    if load_focus is None:
        load_focus = dig(
            status, "mostRecentTrainingLoadBalance", "trainingBalanceFeedbackPhrase"
        )

    # acuteLoad is reported directly on the readiness record; fall back to the
    # training-status block when readiness does not carry it.
    acute_load = pick(readiness, "acuteLoad")
    if acute_load is None and isinstance(latest, dict) and latest:
        acute_load = dig(
            next(iter(latest.values()), None), "acuteTrainingLoadDTO", "acuteTrainingLoad"
        )

    # recoveryTime is in MINUTES, not seconds. Verified against live data: 1908
    # => 31.8 h after an interval session, and a value of 1 coincides with
    # Garmin's own REACHED_ZERO / WELL_RECOVERED feedback.
    recovery_hours = minutes_to_hours(pick(readiness, "recoveryTime"))
    if recovery_hours is None:
        recovery_hours = pick(readiness, "recoveryTimeHours")

    return {
        "training_readiness": pick(readiness, "score"),
        "training_readiness_level": pick(readiness, "level"),
        "recovery_hours": recovery_hours,
        "training_status": training_status_label,
        "acute_load": acute_load,
        "load_focus": load_focus,
        "vo2_max": round(vo2, 1) if isinstance(vo2, (int, float)) else None,
        "fitness_age": fitness_age,
    }


def _body_section(raw: dict[str, Any]) -> dict[str, Any]:
    composition = raw.get("body_composition") or {}
    latest = pick(composition, "totalAverage") or {}
    if not latest:
        entries = pick(composition, "dateWeightList")
        if isinstance(entries, list) and entries:
            latest = entries[-1] or {}

    return {
        "weight_lb": grams_to_pounds(pick(latest, "weight")),
        "bmi": pick(latest, "bmi"),
        "body_fat_percent": pick(latest, "bodyFat"),
        "body_water_percent": pick(latest, "bodyWater"),
        "muscle_mass_lb": grams_to_pounds(pick(latest, "muscleMass")),
    }


def _activity(entry: dict[str, Any], tz: tzinfo) -> dict[str, Any]:
    start = _local_stamp_to_iso(pick(entry, "startTimeLocal"), tz)
    activity_id = pick(entry, "activityId")
    type_key = dig(entry, "activityType", "typeKey")
    avg_speed = pick(entry, "averageSpeed")
    max_speed = pick(entry, "maxSpeed")
    pace_sport = _is_pace_sport(type_key)

    return {
        "id": str(activity_id) if activity_id is not None else None,
        "name": pick(entry, "activityName"),
        "type": type_key,
        "start": start,
        "local_date": start[:10] if start else None,
        "duration_minutes": seconds_to_minutes(pick(entry, "duration")),
        "moving_duration_minutes": seconds_to_minutes(pick(entry, "movingDuration")),
        "distance_miles": meters_to_miles(pick(entry, "distance")),
        "calories": pick(entry, "calories"),
        "avg_hr_bpm": pick(entry, "averageHR"),
        "max_hr_bpm": pick(entry, "maxHR"),
        "avg_pace": mps_to_pace(avg_speed) if pace_sport else None,
        "best_pace": mps_to_pace(max_speed) if pace_sport else None,
        "avg_speed_mph": mps_to_mph(avg_speed),
        "max_speed_mph": mps_to_mph(max_speed),
        "elevation_gain_feet": meters_to_feet(pick(entry, "elevationGain")),
        "elevation_loss_feet": meters_to_feet(pick(entry, "elevationLoss")),
        "aerobic_training_effect": pick(entry, "aerobicTrainingEffect"),
        "anaerobic_training_effect": pick(entry, "anaerobicTrainingEffect"),
        "training_load": pick(entry, "activityTrainingLoad"),
        "avg_cadence": pick(
            entry,
            "averageRunningCadenceInStepsPerMinute",
            "averageBikingCadenceInRevPerMinute",
        ),
        "avg_power_watts": pick(entry, "avgPower", "averagePower"),
        "device": pick(entry, "deviceName"),
    }


def _seven_day_section(activities: list[dict[str, Any]], days: int) -> dict[str, Any]:
    def total(key: str) -> float:
        return sum(
            a[key] for a in activities if isinstance(a.get(key), (int, float))
        )

    def miles_for(*fragments: str) -> float:
        return sum(
            a["distance_miles"]
            for a in activities
            if isinstance(a.get("distance_miles"), (int, float))
            and isinstance(a.get("type"), str)
            and any(f in a["type"] for f in fragments)
        )

    return {
        "window_days": days,
        "workouts": len(activities),
        "activity_minutes": round(total("duration_minutes"), 1),
        "activity_calories": round(total("calories")),
        "running_miles": round(miles_for("running", "treadmill"), 2),
        "cycling_miles": round(miles_for("cycling", "biking"), 2),
        "walking_miles": round(miles_for("walking", "hiking"), 2),
    }


# -------------------------------------------------------------- assembly


def overall_status(results: list[Any]) -> str:
    """OK / PARTIAL / GARMIN_UNAVAILABLE from the per-endpoint outcomes."""
    if not results:
        return "GARMIN_UNAVAILABLE"
    failed = [r for r in results if not r.ok]
    if not failed:
        return "OK"
    if len(failed) == len(results):
        return "GARMIN_UNAVAILABLE"
    return "PARTIAL"


def normalize(
    raw: dict[str, Any],
    results: list[Any],
    *,
    today: date,
    tz: tzinfo,
    lookback_days: int,
    attempted_at: datetime,
) -> dict[str, Any]:
    """Build the versioned normalized payload."""
    status = overall_status(results)

    raw_activities = raw.get("activities")
    if not isinstance(raw_activities, list):
        raw_activities = []
    activities = [_activity(a, tz) for a in raw_activities if isinstance(a, dict)]
    activities.sort(key=lambda a: a["start"] or "", reverse=True)

    return {
        "schema_version": SCHEMA_VERSION,
        "sync": {
            "status": status,
            "last_attempt": attempted_at.isoformat(),
            # Phase 1 has no persistence, so the current run is the only
            # success this process can know about. Phase 2 carries a real
            # last_success across runs.
            "last_success": (
                attempted_at.isoformat() if status != "GARMIN_UNAVAILABLE" else None
            ),
            "timezone": timezone_label(tz),
            "unavailable_endpoints": sorted(r.key for r in results if not r.ok),
            "empty_endpoints": sorted(r.key for r in results if r.ok and r.empty),
        },
        "today": _today_section(raw, today),
        "sleep": _sleep_section(raw, tz),
        "recovery": _recovery_section(raw),
        "body": _body_section(raw),
        "recent_activities": activities,
        "seven_day": _seven_day_section(activities, lookback_days),
    }
