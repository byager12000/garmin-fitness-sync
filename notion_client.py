"""Notion adapter layer (Phase 3).

Every Notion API call lives here. Uses the REST API through `requests`
directly rather than an SDK: it is one dependency fewer, and `requests` is
pure Python, which matters because the Phase 5 runtime is already fighting a
C-extension problem with curl_cffi.

Page update strategy -- the page has a **managed section**, everything after
the first divider block. Each run replaces that section rather than appending
blocks forever, so the page never grows without bound and its headings stay
stable for retrieval.

The replacement is append-then-delete, deliberately:

* append new blocks, then delete the old ones
* if the delete fails, the page briefly shows duplicated content -- ugly, but
  nothing is lost
* the reverse order would risk an empty page if the append failed

Notion has no transactions, so failing safe is the best available guarantee.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
TIMEOUT = 30

# Bounded exponential backoff. Only transient conditions are retried: a bad
# token or a missing page will never succeed on a retry, so those fail fast.
MAX_ATTEMPTS = 4
BASE_DELAY = 1.0
MAX_DELAY = 16.0
RETRY_STATUS = {429, 500, 502, 503, 504}

# Notion rejects any single rich_text item over 2000 characters.
RICH_TEXT_LIMIT = 1900
# Notion accepts at most 100 children per append request.
APPEND_CHUNK = 100


class NotionError(Exception):
    """Notion could not be reached or refused the request."""


class NotionPageNotFound(NotionError):
    """The Fitness Live page is not visible to this integration."""


# ------------------------------------------------------------ block helpers


def _text(content: str, *, bold: bool = False, code: bool = False) -> dict[str, Any]:
    return {
        "type": "text",
        "text": {"content": content[:RICH_TEXT_LIMIT]},
        "annotations": {"bold": bold, "code": code},
    }


def heading(text: str, level: int = 2) -> dict[str, Any]:
    key = f"heading_{level}"
    return {"object": "block", "type": key, key: {"rich_text": [_text(text)]}}


def paragraph(text: str = "") -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [_text(text)] if text else []},
    }


def bullet(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [_text(text)]},
    }


def callout(text: str, emoji: str = "⚠️") -> dict[str, Any]:
    return {
        "object": "block",
        "type": "callout",
        "callout": {"rich_text": [_text(text)], "icon": {"type": "emoji", "emoji": emoji}},
    }


def code_block(content: str, language: str = "json") -> dict[str, Any]:
    """A code block, split across rich_text items to respect the 2000 cap."""
    chunks = [
        content[i : i + RICH_TEXT_LIMIT] for i in range(0, len(content), RICH_TEXT_LIMIT)
    ] or [""]
    return {
        "object": "block",
        "type": "code",
        "code": {
            "rich_text": [_text(chunk) for chunk in chunks],
            "language": language,
        },
    }


def table_rows(pairs: list[tuple[str, Any]]) -> list[dict[str, Any]]:
    """Render label/value pairs as bullets.

    Bullets rather than a Notion table: they survive round-tripping into plain
    text far better, and this page is read by a model first and a human second.
    """
    out = []
    for label, value in pairs:
        shown = "-" if value is None else value
        out.append(bullet(f"{label}: {shown}"))
    return out


# ----------------------------------------------------------------- adapter


class NotionAdapter:
    def __init__(self, token: str, *, page_id: str | None = None, page_title: str = "Fitness Live"):
        if not token:
            raise NotionError("NOTION_TOKEN is not set")
        self.token = token
        self.page_id = page_id
        self.page_title = page_title
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            }
        )

    # -- plumbing ---------------------------------------------------------

    def _backoff(self, attempt: int, retry_after: str | None = None) -> float:
        """Delay before the next attempt, honouring Retry-After when present."""
        if retry_after:
            try:
                return min(float(retry_after), MAX_DELAY)
            except ValueError:
                pass
        delay = min(BASE_DELAY * (2 ** (attempt - 1)), MAX_DELAY)
        # Jitter so repeated failures do not resynchronise into a thundering herd.
        return delay * (0.5 + random.random() / 2)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{API}{path}"
        last_error = "unknown error"

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self._session.request(method, url, timeout=TIMEOUT, **kwargs)
            except requests.RequestException as exc:
                last_error = f"could not reach Notion: {exc}"
                if attempt == MAX_ATTEMPTS:
                    break
                delay = self._backoff(attempt)
                logger.warning(
                    "notion request failed (%s), retrying in %.1fs [%d/%d]",
                    exc,
                    delay,
                    attempt,
                    MAX_ATTEMPTS,
                )
                time.sleep(delay)
                continue

            if response.status_code in RETRY_STATUS:
                last_error = (
                    f"Notion returned {response.status_code}: {response.text[:300]}"
                )
                if attempt == MAX_ATTEMPTS:
                    break
                delay = self._backoff(attempt, response.headers.get("Retry-After"))
                logger.warning(
                    "notion returned %d, retrying in %.1fs [%d/%d]",
                    response.status_code,
                    delay,
                    attempt,
                    MAX_ATTEMPTS,
                )
                time.sleep(delay)
                continue

            if response.status_code >= 400:
                # A 401/403/404 will not improve on a retry -- fail fast.
                # Surface Notion's own message, which is usually specific, but
                # never echo the Authorization header back into a log.
                raise NotionError(
                    f"Notion returned {response.status_code}: {response.text[:300]}"
                )

            if not response.content:
                return {}
            return response.json()

        raise NotionError(f"{last_error} (after {MAX_ATTEMPTS} attempts)")

    # -- page lookup ------------------------------------------------------

    def resolve_page_id(self) -> str:
        """Find the managed page, by explicit ID or by title."""
        if self.page_id:
            # Confirm it is actually reachable before we try to write to it.
            self._request("GET", f"/pages/{self.page_id}")
            logger.info("using configured Notion page id")
            return self.page_id

        payload = {
            "query": self.page_title,
            "filter": {"value": "page", "property": "object"},
        }
        results = self._request("POST", "/search", json=payload).get("results", [])
        for page in results:
            title_prop = (page.get("properties") or {}).get("title", {})
            parts = title_prop.get("title") or []
            name = "".join(part.get("plain_text", "") for part in parts).strip()
            if name.casefold() == self.page_title.casefold():
                self.page_id = page["id"]
                logger.info("resolved Notion page %r by title", self.page_title)
                return self.page_id

        raise NotionPageNotFound(
            f"No page titled {self.page_title!r} is visible to this integration. "
            "Create the page, then share it with the integration: open the page, "
            "click the ... menu, choose Connections, and connect it."
        )

    # -- managed section --------------------------------------------------

    def _children(self, block_id: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            path = f"/blocks/{block_id}/children?page_size=100"
            if cursor:
                path += f"&start_cursor={cursor}"
            data = self._request("GET", path)
            blocks.extend(data.get("results", []))
            if not data.get("has_more"):
                return blocks
            cursor = data.get("next_cursor")

    def _managed_block_ids(self, page_id: str) -> list[str]:
        """IDs of every block after the first divider -- the managed section."""
        blocks = self._children(page_id)
        for index, block in enumerate(blocks):
            if block.get("type") == "divider":
                return [b["id"] for b in blocks[index + 1 :]]
        # No divider: treat the page as unmanaged and append below everything,
        # replacing nothing. The divider gets written on the first sync.
        return []

    def _append(self, page_id: str, blocks: list[dict[str, Any]]) -> None:
        for start in range(0, len(blocks), APPEND_CHUNK):
            chunk = blocks[start : start + APPEND_CHUNK]
            self._request("PATCH", f"/blocks/{page_id}/children", json={"children": chunk})

    def _has_divider(self, page_id: str) -> bool:
        return any(b.get("type") == "divider" for b in self._children(page_id))

    def replace_managed_section(self, page_id: str, blocks: list[dict[str, Any]]) -> None:
        """Swap the managed section for `blocks`, appending before deleting."""
        if not self._has_divider(page_id):
            logger.info("no divider on page; creating the managed section marker")
            self._append(page_id, [{"object": "block", "type": "divider", "divider": {}}])

        stale_ids = self._managed_block_ids(page_id)
        self._append(page_id, blocks)

        # Only now remove the previous content. A failure here leaves the page
        # duplicated rather than empty.
        failed = 0
        for block_id in stale_ids:
            try:
                self._request("DELETE", f"/blocks/{block_id}")
            except NotionError as exc:
                failed += 1
                logger.warning("could not delete stale block: %s", exc)
        if failed:
            logger.warning(
                "%d stale block(s) survived; page may show duplicated content", failed
            )
        logger.info("replaced managed section (%d new blocks)", len(blocks))
