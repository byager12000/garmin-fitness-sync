"""Single-instance lock (Phase 4).

An hourly scheduler will eventually fire while a previous run is still going --
a slow network, a phone that woke up late. Two syncs racing each other would
interleave writes to `latest.json` and to the Notion page, so the second run
must notice and step aside quietly.

**Why this does not check whether the holding PID is alive on Windows.**
The obvious trick is `os.kill(pid, 0)`. On POSIX that is a harmless liveness
probe. On Windows, Python's `os.kill` has no signal semantics -- it calls
`TerminateProcess`, so `os.kill(pid, 0)` would *kill* the process it was meant
to ask about. This module therefore uses a PID probe only on POSIX, and relies
on lock age everywhere else.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from types import TracebackType

logger = logging.getLogger(__name__)

LOCK_PATH = Path("run.lock")
# A sync that has not finished within this long is assumed dead -- a killed
# process or a phone that was hard-rebooted mid-run leaves the file behind.
DEFAULT_STALE_AFTER = 30 * 60


class LockHeld(Exception):
    """Another sync is already running."""


def _pid_alive(pid: int) -> bool | None:
    """True/False on POSIX, None on Windows where it cannot be asked safely."""
    if os.name == "nt":
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but belongs to another user.
        return True
    except OSError:
        return None
    return True


class RunLock:
    """Cooperative lock held for the duration of one sync."""

    def __init__(
        self,
        path: Path = LOCK_PATH,
        stale_after: float = DEFAULT_STALE_AFTER,
    ) -> None:
        self.path = path
        self.stale_after = stale_after
        self._acquired = False

    # -- internals --------------------------------------------------------

    def _write(self, fd: int) -> None:
        payload = json.dumps(
            {"pid": os.getpid(), "started": time.time(), "argv": " ".join(sys.argv[:2])}
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)

    def _read(self) -> dict[str, object]:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            # An unreadable lock is treated as suspect; age decides.
            return {}

    def _is_stale(self) -> bool:
        info = self._read()

        pid = info.get("pid")
        if isinstance(pid, int):
            alive = _pid_alive(pid)
            if alive is False:
                logger.warning("lock held by dead pid %s; reclaiming", pid)
                return True

        try:
            age = time.time() - self.path.stat().st_mtime
        except OSError:
            return True
        if age > self.stale_after:
            logger.warning(
                "lock is %.0f s old (limit %.0f s); assuming the holder died",
                age,
                self.stale_after,
            )
            return True
        return False

    # -- api --------------------------------------------------------------

    def acquire(self) -> None:
        """Take the lock, or raise LockHeld. Creation is atomic (O_EXCL)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if not self._is_stale():
                info = self._read()
                raise LockHeld(
                    f"another sync is already running (pid {info.get('pid', '?')}); "
                    "exiting without doing anything"
                ) from None
            # Stale: remove and try once more. If that second attempt also
            # collides, a genuine competitor won the race -- let it have it.
            self.path.unlink(missing_ok=True)
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                raise LockHeld(
                    "another sync claimed the lock while this one was clearing "
                    "a stale file; exiting"
                ) from None

        self._write(fd)
        self._acquired = True
        logger.debug("acquired run lock (pid %d)", os.getpid())

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("could not remove lock file: %s", exc)
        self._acquired = False
        logger.debug("released run lock")

    def __enter__(self) -> "RunLock":
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # Always release, including on crash, so one bad run does not block
        # every later run until the staleness timeout expires.
        self.release()
