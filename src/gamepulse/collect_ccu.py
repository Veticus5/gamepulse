"""Collect the current player count (CCU) for every tracked game."""

import logging
import time
from pathlib import Path

import httpx

from gamepulse.config import Game
from gamepulse.steam import SteamError, fetch_ccu
from gamepulse.storage import append_jsonl, utc_now_iso

log = logging.getLogger(__name__)


def run(client: httpx.Client, games: list[Game], data_dir: Path, *, pause: float = 0.2) -> int:
    """Append one measurement per game; return how many games succeeded.

    A failed request is recorded too (``ok: false``), which later tells
    "Steam did not answer" apart from "the collector was not running".
    """
    succeeded = 0
    for index, game in enumerate(games):
        if index and pause:
            time.sleep(pause)
        ts = utc_now_iso()
        try:
            record = {
                "ts": ts,
                "appid": game.appid,
                "player_count": fetch_ccu(client, game.appid),
                "ok": True,
                "error": None,
            }
            succeeded += 1
        except SteamError as exc:
            log.warning("ccu %s (%s): %s", game.appid, game.name, exc)
            record = {
                "ts": ts,
                "appid": game.appid,
                "player_count": None,
                "ok": False,
                "error": str(exc),
            }
        append_jsonl(data_dir / "raw" / "ccu" / f"{ts[:10]}.jsonl", [record])
    log.info("ccu: %d/%d games ok", succeeded, len(games))
    return succeeded
