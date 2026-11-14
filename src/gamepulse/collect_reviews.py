"""Collect the review histogram (positive/negative counts over time)."""

import logging
import time
from pathlib import Path

import httpx

from gamepulse.config import Game
from gamepulse.steam import SteamError, fetch_review_histogram
from gamepulse.storage import append_jsonl, utc_now_iso

log = logging.getLogger(__name__)


def run(client: httpx.Client, games: list[Game], data_dir: Path, *, pause: float = 0.2) -> int:
    """Append one full snapshot per game; return how many games succeeded.

    Every snapshot repeats the whole history. Picking the latest value per
    day is left to the modelling layer; raw files stay append-only.
    """
    succeeded = 0
    for index, game in enumerate(games):
        if index and pause:
            time.sleep(pause)
        try:
            results = fetch_review_histogram(client, game.appid)
            append_jsonl(
                data_dir / "raw" / "review_histogram" / f"{game.appid}.jsonl",
                [{"fetched_at": utc_now_iso(), "appid": game.appid, "results": results}],
            )
        except SteamError as exc:
            log.warning("reviews %s (%s): %s", game.appid, game.name, exc)
            continue
        except Exception:
            log.exception("reviews %s (%s): unexpected error", game.appid, game.name)
            continue
        succeeded += 1
    log.info("reviews: %d/%d games ok", succeeded, len(games))
    return succeeded
