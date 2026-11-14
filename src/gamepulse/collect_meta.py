"""Collect store metadata for every tracked game (studio, release date, genres)."""

import logging
import time
from pathlib import Path

import httpx

from gamepulse.config import Game
from gamepulse.steam import SteamError, fetch_app_details
from gamepulse.storage import append_jsonl, utc_now_iso

log = logging.getLogger(__name__)

# The full store response is large (descriptions, screenshots, requirements);
# only what the interface shows is kept.
FIELDS = (
    "name",
    "type",
    "is_free",
    "developers",
    "publishers",
    "release_date",
    "genres",
    "header_image",
    "short_description",
    "recommendations",
    "price_overview",
    "metacritic",
    "website",
)


def run(client: httpx.Client, games: list[Game], data_dir: Path, *, pause: float = 1.0) -> int:
    """Append one metadata snapshot per game; return how many games succeeded."""
    succeeded = 0
    for index, game in enumerate(games):
        if index and pause:
            time.sleep(pause)
        try:
            data = fetch_app_details(client, game.appid)
            record = {
                "fetched_at": utc_now_iso(),
                "appid": game.appid,
                "details": {key: data.get(key) for key in FIELDS},
            }
            append_jsonl(data_dir / "raw" / "appdetails" / f"{game.appid}.jsonl", [record])
        except SteamError as exc:
            log.warning("meta %s (%s): %s", game.appid, game.name, exc)
            continue
        except Exception:
            log.exception("meta %s (%s): unexpected error", game.appid, game.name)
            continue
        succeeded += 1
    log.info("meta: %d/%d games ok", succeeded, len(games))
    return succeeded
