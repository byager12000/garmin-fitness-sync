"""Local persistence for the normalized snapshot (Phase 2).

Two jobs, both about not losing good data:

* Write `data/latest.json` **atomically** -- temp file then rename -- so a
  crash or a pulled battery mid-write can never leave a half-written snapshot
  where the last good one used to be.
* **Preserve the last known good data.** If Garmin fails to answer for a whole
  section this run, that section is restored from the previous snapshot and
  flagged as stale rather than blanked out. A failed sync must never destroy
  working data.

Log rotation, retry/backoff and locking are deliberately NOT here -- those are
Phase 4.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
LOG_DIR = Path("logs")
SNAPSHOT_PATH = DATA_DIR / "latest.json"
LOG_PATH = LOG_DIR / "sync.log"

# Capped so an hourly job cannot fill a phone: ~2 MB total.
LOG_MAX_BYTES = 512 * 1024
LOG_BACKUPS = 3

# Which Garmin endpoints feed which section of the normalized payload. A
# section is only restored from the previous snapshot when *every* endpoint
# behind it failed -- a partial answer is still real data and is kept.
SECTION_SOURCES: dict[str, tuple[str, ...]] = {
    "today": (
        "user_summary",
        "stress",
        "intensity_minutes",
        "floors",
        "body_battery",
        "resting_hr",
    ),
    "sleep": ("sleep", "hrv"),
    "recovery": ("training_readiness", "training_status", "max_metrics"),
    "body": ("body_composition",),
    "recent_activities": ("activities",),
    "seven_day": ("activities",),
}


def setup_logging(verbose: bool = False) -> None:
    """Log to logs/sync.log, and to stderr at WARNING (or DEBUG if verbose).

    The file handler rotates, so an hourly job running for months cannot fill
    the phone's storage: 512 KB per file, 3 older files kept, ~2 MB ceiling.

    Never log a secret: this program only ever logs statuses, endpoint names
    and counts.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for handler in list(root.handlers):
        handler.close()
        root.removeHandler(handler)

    file_handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUPS,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    root.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
    stream_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(stream_handler)


def load_previous(path: Path = SNAPSHOT_PATH) -> dict[str, Any] | None:
    """Read the last snapshot. A missing or corrupt file is not fatal."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        logger.info("no previous snapshot at %s (first run?)", path)
        return None
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("previous snapshot at %s is unreadable: %s", path, exc)
        return None

    if not isinstance(data, dict):
        logger.warning("previous snapshot at %s is not an object; ignoring", path)
        return None
    return data


def write_atomic(payload: dict[str, Any], path: Path = SNAPSHOT_PATH) -> None:
    """Write JSON to `path` atomically: temp file in the same dir, then rename.

    The temp file must share a filesystem with the target for os.replace to be
    atomic, hence writing it into the same directory.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    tmp_path = Path(handle.name)
    try:
        with handle:
            json.dump(payload, handle, indent=2, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        # Never leave a stray temp file behind on failure.
        tmp_path.unlink(missing_ok=True)
        raise
    logger.info("wrote snapshot to %s", path)


def _failed_keys(results: list[Any]) -> set[str]:
    return {r.key for r in results if not r.ok}


def finalize(
    payload: dict[str, Any],
    previous: dict[str, Any] | None,
    results: list[Any],
) -> dict[str, Any]:
    """Merge this run with the last good snapshot and fix up the sync block.

    Sections whose every source endpoint failed are restored from `previous`
    and listed in `sync.stale_sections`, so a consumer can tell fresh data from
    carried-over data. `last_success` only advances when this run actually
    produced data.
    """
    sync = payload["sync"]
    status = sync["status"]
    failed = _failed_keys(results)
    stale: list[str] = []

    if previous:
        for section, sources in SECTION_SOURCES.items():
            if not sources or not all(src in failed for src in sources):
                continue
            if section not in previous:
                continue
            payload[section] = previous[section]
            stale.append(section)
            logger.warning(
                "section %r restored from previous snapshot (sources failed: %s)",
                section,
                ", ".join(sorted(sources)),
            )

    sync["stale_sections"] = sorted(set(stale))

    produced_data = status in ("OK", "PARTIAL")
    if produced_data:
        sync["last_success"] = sync["last_attempt"]
    else:
        # Carry the previous success forward; this run achieved nothing.
        sync["last_success"] = (previous or {}).get("sync", {}).get("last_success")

    if stale and status == "PARTIAL":
        sync["previous_snapshot_date"] = (
            (previous or {}).get("today", {}).get("date")
        )
    return payload


def failure_snapshot(
    previous: dict[str, Any] | None,
    *,
    status: str,
    attempted_at: datetime,
    detail: str | None = None,
) -> dict[str, Any] | None:
    """Build a snapshot for a run that produced no data at all.

    Keeps every previously-good section untouched and updates only the sync
    block, so an auth failure or an offline phone never erases working data.
    Returns None when there is nothing to preserve (nothing written).
    """
    if not previous:
        logger.info("run failed (%s) and no previous snapshot exists; nothing to write", status)
        return None

    snapshot = dict(previous)
    sync = dict(snapshot.get("sync", {}))
    sync["status"] = status
    sync["last_attempt"] = attempted_at.isoformat()
    sync["stale_sections"] = sorted(SECTION_SOURCES)
    if detail:
        # Statuses and endpoint names only -- never a token or password.
        sync["last_error"] = detail
    snapshot["sync"] = sync
    logger.warning("run failed (%s); preserving previous data, updating sync only", status)
    return snapshot
