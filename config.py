"""Configuration for the Garmin -> Notion fitness sync.

Phase 1 scope: Garmin credentials, token store location, the rolling activity
window, and local-timezone resolution. Notion settings arrive in Phase 3.

Nothing in here is allowed to print or log a secret.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Bumped whenever the normalized JSON contract changes shape.
SCHEMA_VERSION = 1

DEFAULT_TOKENSTORE = "~/.garminconnect"
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_NOTION_PAGE_TITLE = "Fitness Live"


def _system_timezone() -> tzinfo:
    local = datetime.now().astimezone().tzinfo
    if local is None:  # pragma: no cover - astimezone() always attaches one
        return timezone.utc
    return local


def _local_timezone(override: str | None = None) -> tzinfo:
    """Resolve the timezone used for current-day boundaries.

    Defaults to whatever the machine (phone) is currently set to, so a travel
    day follows the traveller instead of a hard-coded US timezone. FITNESS_TZ
    exists only to make behaviour reproducible in testing.

    An unusable override never takes the sync down: a bad zone name, or a
    platform with no IANA database (bare Windows without `tzdata`), falls back
    to the system zone with a warning.
    """
    if override:
        try:
            return ZoneInfo(override)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            logger.warning(
                "FITNESS_TZ=%r is not a usable timezone (%s); using system zone",
                override,
                exc,
            )
    return _system_timezone()


def timezone_label(tz: tzinfo) -> str:
    """Human/machine readable name for a timezone, IANA key when available."""
    key = getattr(tz, "key", None)
    if key:
        return str(key)
    return datetime.now(tz).tzname() or str(tz)


@dataclass
class Config:
    """Runtime configuration. Secrets stay in memory, never in the payload."""

    email: str | None = None
    password: str | None = None
    tokenstore: str = DEFAULT_TOKENSTORE
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    timezone: tzinfo = field(default_factory=_local_timezone)
    notion_token: str | None = None
    notion_page_id: str | None = None
    notion_page_title: str = DEFAULT_NOTION_PAGE_TITLE

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()

        def env(name: str) -> str | None:
            """Read a setting, tolerating stray whitespace from hand-editing."""
            value = os.getenv(name)
            return value.strip() if value else None

        raw_days = env("ACTIVITY_LOOKBACK_DAYS") or str(DEFAULT_LOOKBACK_DAYS)
        try:
            lookback = max(0, int(raw_days))
        except ValueError:
            lookback = DEFAULT_LOOKBACK_DAYS
        return cls(
            email=env("GARMIN_EMAIL"),
            password=env("GARMIN_PASSWORD"),
            tokenstore=env("GARMINTOKENS") or DEFAULT_TOKENSTORE,
            lookback_days=lookback,
            timezone=_local_timezone(env("FITNESS_TZ")),
            notion_token=env("NOTION_TOKEN"),
            notion_page_id=env("NOTION_PAGE_ID"),
            notion_page_title=env("NOTION_PAGE_TITLE") or DEFAULT_NOTION_PAGE_TITLE,
        )

    @property
    def tokenstore_path(self) -> Path:
        return Path(self.tokenstore).expanduser()

    @property
    def has_credentials(self) -> bool:
        return bool(self.email and self.password)

    @property
    def has_stored_tokens(self) -> bool:
        return self.tokenstore_path.exists()

    @property
    def notion_configured(self) -> bool:
        return bool(self.notion_token)
