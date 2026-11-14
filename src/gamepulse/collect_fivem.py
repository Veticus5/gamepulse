"""Collect FiveM's own total player counts.

FiveM (the GTA V multiplayer mod) has no usable player count on Steam, so
this reads two small JSON files served by the FiveM project itself. Both
were found on 2026-11-14 and are undocumented: each returns a list of three
numbers whose meaning is not confirmed. The raw lists are stored as they
come; interpreting them is left for later, once there is some history.
"""

import logging
import time
from pathlib import Path

import httpx

from gamepulse.steam import FetchError, get_json
from gamepulse.storage import append_jsonl, utc_now_iso

log = logging.getLogger(__name__)

SOURCES = (
    "https://static.cfx.re/runtime/counts.json",
    "https://runtime.fivem.net/counts.json",
)


def _fetch_counts(client: httpx.Client, url: str) -> list:
    body = get_json(client, url)
    numbers = (int, float, type(None))
    if (
        not isinstance(body, list)
        or not body
        or not all(isinstance(v, numbers) and not isinstance(v, bool) for v in body)
    ):
        raise FetchError("unexpected counts format")
    return body


def run(client: httpx.Client, data_dir: Path, *, pause: float = 0.2) -> int:
    """Append one record per source; return how many sources succeeded."""
    succeeded = 0
    for index, url in enumerate(SOURCES):
        if index and pause:
            time.sleep(pause)
        ts = utc_now_iso()
        try:
            record = {"ts": ts, "url": url, "counts": _fetch_counts(client, url), "ok": True, "error": None}
            succeeded += 1
        except FetchError as exc:
            log.warning("fivem %s: %s", url, exc)
            record = {"ts": ts, "url": url, "counts": None, "ok": False, "error": str(exc)}
        append_jsonl(data_dir / "raw" / "fivem" / f"{ts[:10]}.jsonl", [record])
    log.info("fivem: %d/%d sources ok", succeeded, len(SOURCES))
    return succeeded
