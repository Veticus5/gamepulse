"""Collect the store price and discount of every tracked game.

A discount often explains a wave of new reviews or players, and Steam
keeps no history of it, so it is recorded with every player-count run.
Prices are the US store's; the discount percentage is what matters.
"""

import logging
from pathlib import Path

import httpx

from gamepulse.config import Game
from gamepulse.steam import SteamError, fetch_prices
from gamepulse.storage import append_jsonl, utc_now_iso

log = logging.getLogger(__name__)


def run(client: httpx.Client, games: list[Game], data_dir: Path) -> int:
    """Append one row per game that Steam answered for; return how many."""
    ts = utc_now_iso()
    try:
        prices = fetch_prices(client, [game.appid for game in games])
    except SteamError as exc:
        log.warning("prices: %s", exc)
        return 0
    rows = []
    for game in games:
        if game.appid not in prices:
            continue
        price = prices[game.appid] or {}
        rows.append({
            "ts": ts,
            "appid": game.appid,
            "priced": bool(price),  # false: free to play or not for sale
            "currency": price.get("currency"),
            "initial": price.get("initial"),
            "final": price.get("final"),
            "discount_percent": price.get("discount_percent"),
        })
    append_jsonl(data_dir / "raw" / "prices" / f"{ts[:10]}.jsonl", rows)
    log.info("prices: %d/%d games ok", len(rows), len(games))
    return len(rows)
