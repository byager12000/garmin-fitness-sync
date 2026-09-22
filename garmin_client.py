"""Garmin adapter layer.

Every call into the unofficial `garminconnect` package happens here and nowhere
else. The rest of the program talks to raw dicts and the normalized schema, so
a Garmin API change is contained to this file.

Verified against garminconnect 0.3.16 (2026-09-22). Note that 0.3.x dropped
`garth` entirely -- there is no `.garth` attribute and old garth token stores
are not readable. See PHASE0-FINDINGS.md.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from config import Config

logger = logging.getLogger(__name__)


class GarminAuthRequired(Exception):
    """Raised when no usable token store exists and credentials cannot log in.

    The caller should surface AUTH_REQUIRED and stop; retrying an auth failure
    in a loop is how accounts get rate-limited or locked.
    """


@dataclass
class EndpointResult:
    """Outcome of a single Garmin endpoint call."""

    key: str
    ok: bool
    error: str | None = None
    empty: bool = False

    @property
    def status(self) -> str:
        if not self.ok:
            return "ERROR"
        return "EMPTY" if self.empty else "OK"


class GarminAdapter:
    """Thin, defensive wrapper over the Garmin Connect client."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._client: Garmin | None = None
        self.used_stored_tokens = False
        self._prompt_mfa: Callable[[], str] | None = None
        # A token can expire mid-run. One silent re-login is allowed per run;
        # more than that would be an auth-retry loop, which is how accounts
        # get rate-limited or locked.
        self._reauth_used = False
        self.reauthenticated = False

    # ---------------------------------------------------------------- auth

    def connect(self, prompt_mfa: Callable[[], str] | None = None) -> None:
        """Authenticate, preferring the stored token store over a fresh login.

        `Garmin.login(tokenstore)` loads and proactively refreshes stored
        tokens; only if that fails does it fall back to username/password and
        then persist fresh tokens back to the same path.
        """
        self._prompt_mfa = prompt_mfa
        had_tokens = self.cfg.has_stored_tokens
        if not had_tokens and not self.cfg.has_credentials:
            raise GarminAuthRequired(
                "No stored tokens at "
                f"{self.cfg.tokenstore_path} and no GARMIN_EMAIL/GARMIN_PASSWORD set. "
                "Run the first login interactively to create the token store."
            )

        # retry_attempts is the library's own bounded retry for transient
        # Garmin errors, so this adapter deliberately does not wrap every data
        # call in a second retry loop -- that would multiply out to a burst of
        # requests against an API that already rate-limits by IP.
        client = Garmin(
            email=self.cfg.email,
            password=self.cfg.password,
            prompt_mfa=prompt_mfa,
            retry_attempts=3,
            retry_min_wait=1.0,
            retry_max_wait=10.0,
        )
        try:
            client.login(str(self.cfg.tokenstore_path))
        except GarminConnectAuthenticationError as exc:
            raise GarminAuthRequired(f"Garmin rejected the login: {exc}") from exc
        except GarminConnectTooManyRequestsError as exc:
            raise GarminAuthRequired(
                f"Garmin is rate-limiting this account; wait before retrying: {exc}"
            ) from exc

        self._client = client
        # If tokens already existed and login() succeeded without needing
        # credentials, the stored session was reused.
        self.used_stored_tokens = had_tokens

    @property
    def client(self) -> Garmin:
        if self._client is None:
            raise RuntimeError("connect() must be called before fetching data")
        return self._client

    def display_name(self) -> str | None:
        return getattr(self._client, "display_name", None)

    # --------------------------------------------------------------- fetch

    def _try_reauth(self) -> bool:
        """Re-login once per run after a mid-run token expiry."""
        if self._reauth_used:
            return False
        self._reauth_used = True
        logger.warning("Garmin token appears to have expired; re-authenticating once")
        try:
            self.connect(prompt_mfa=self._prompt_mfa)
        except Exception as exc:
            logger.warning("re-authentication failed: %s", exc)
            return False
        self.reauthenticated = True
        logger.info("re-authentication succeeded; retrying the failed endpoint")
        return True

    def _safe(
        self,
        results: list[EndpointResult],
        key: str,
        fn: Callable[[], Any],
    ) -> Any | None:
        """Call one endpoint. A failure is recorded, never raised.

        A single unavailable metric must not take the whole sync down -- some
        metrics simply do not exist on every watch or account.
        """
        try:
            value = fn()
        except GarminConnectAuthenticationError as exc:
            # The stored token expired partway through the run. Refresh once
            # and retry this endpoint; never loop on an auth failure.
            logger.debug("%s: authentication error: %s", key, exc)
            if self._try_reauth():
                try:
                    value = fn()
                except Exception as retry_exc:
                    logger.debug("%s: failed again after re-auth: %s", key, retry_exc)
                    results.append(
                        EndpointResult(
                            key, ok=False, error=f"after re-auth: {type(retry_exc).__name__}"
                        )
                    )
                    return None
                empty = value is None or (isinstance(value, (list, dict)) and not value)
                results.append(EndpointResult(key, ok=True, empty=empty))
                return value
            results.append(
                EndpointResult(key, ok=False, error="GarminConnectAuthenticationError")
            )
            return None
        except (
            GarminConnectConnectionError,
            GarminConnectTooManyRequestsError,
        ) as exc:
            logger.debug("%s: connection/rate-limit failure: %s", key, exc)
            results.append(EndpointResult(key, ok=False, error=type(exc).__name__))
            return None
        except Exception as exc:  # unofficial API: anything can come back
            logger.debug("%s: unexpected failure: %s", key, exc)
            results.append(
                EndpointResult(key, ok=False, error=f"{type(exc).__name__}: {exc}")
            )
            return None

        empty = value is None or (isinstance(value, (list, dict)) and not value)
        results.append(EndpointResult(key, ok=True, empty=empty))
        return value

    def fetch_raw(
        self, today: date, window_start: date
    ) -> tuple[dict[str, Any], list[EndpointResult]]:
        """Fetch every Phase 1 endpoint. Returns (raw payloads, per-endpoint status)."""
        c = self.client
        t = today.isoformat()
        s = window_start.isoformat()
        results: list[EndpointResult] = []

        raw = {
            "user_summary": self._safe(results, "user_summary", lambda: c.get_user_summary(t)),
            "sleep": self._safe(results, "sleep", lambda: c.get_sleep_data(t)),
            "hrv": self._safe(results, "hrv", lambda: c.get_hrv_data(t)),
            "body_battery": self._safe(results, "body_battery", lambda: c.get_body_battery(t, t)),
            "training_readiness": self._safe(
                results, "training_readiness", lambda: c.get_training_readiness(t)
            ),
            "training_status": self._safe(
                results, "training_status", lambda: c.get_training_status(t)
            ),
            "resting_hr": self._safe(results, "resting_hr", lambda: c.get_rhr_day(t)),
            "stress": self._safe(results, "stress", lambda: c.get_all_day_stress(t)),
            "intensity_minutes": self._safe(
                results, "intensity_minutes", lambda: c.get_intensity_minutes_data(t)
            ),
            "floors": self._safe(results, "floors", lambda: c.get_floors(t)),
            "max_metrics": self._safe(results, "max_metrics", lambda: c.get_max_metrics(t)),
            "body_composition": self._safe(
                results, "body_composition", lambda: c.get_body_composition(s, t)
            ),
            "activities": self._safe(
                results, "activities", lambda: c.get_activities_by_date(s, t)
            ),
        }
        return raw, results
