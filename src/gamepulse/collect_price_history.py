"""Fetch the Steam price history of every tracked game from IsThereAnyDeal.

Steam only tells today's price, so discounts from before the collection
started are unknown; IsThereAnyDeal keeps a log of price changes. Each run
asks for the whole window again and replaces the game's file, so the file
is always one consistent log. Historical prices: IsThereAnyDeal.com.
"""

import json
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from gamepulse.config import Game

log = logging.getLogger(__name__)

API_BASE = "https://api.isthereanydeal.com"
STEAM_SHOP = 61
KEY_NAME = "ITAD_API_KEY"
STAMP = "%Y-%m-%dT%H:%M:%SZ"


class ItadError(Exception):
    """A request failed; `fatal` means the next one would fail the same way."""

    def __init__(self, message: str, fatal: bool = False):
        super().__init__(message)
        self.fatal = fatal


def api_key(env_file: Path = Path(".env")) -> str | None:
    """The key from the environment or, failing that, from the local .env file."""
    if os.environ.get(KEY_NAME):
        return os.environ[KEY_NAME]
    try:
        lines = env_file.read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        name, _, value = line.partition("=")
        if name.strip() == KEY_NAME and value.strip():
            return value.strip()
    return None


def _get(client: httpx.Client, key: str, path: str, params: dict):
    try:
        response = client.get(f"{API_BASE}{path}", params=params, headers={"ITAD-API-Key": key})
    except httpx.HTTPError as exc:
        raise ItadError(f"{type(exc).__name__}") from exc
    if response.status_code in (401, 403, 429):
        raise ItadError(f"HTTP {response.status_code}", fatal=True)
    if response.status_code != 200:
        raise ItadError(f"HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise ItadError("not JSON") from exc


def _rows(changes, appid: int, fetched_at: str, since: str) -> list[dict]:
    rows = []
    for change in changes if isinstance(changes, list) else []:
        try:
            if change["shop"]["id"] != STEAM_SHOP:
                continue
            deal = change["deal"]
            rows.append({
                "fetched_at": fetched_at,
                "since": since,
                "appid": appid,
                "ts": datetime.fromisoformat(change["timestamp"]).astimezone(UTC).strftime(STAMP),
                "currency": deal["price"]["currency"],
                "initial": int(deal["regular"]["amountInt"]),
                "final": int(deal["price"]["amountInt"]),
                "discount_percent": int(deal["cut"]),
            })
        except (KeyError, TypeError, ValueError):
            continue  # a change in a shape we do not know is left out, not guessed
    return sorted(rows, key=lambda row: row["ts"])


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows))
    tmp.replace(path)


def run(
    client: httpx.Client,
    games: list[Game],
    data_dir: Path,
    *,
    key: str,
    days: int = 400,
    pause: float = 0.5,
    now: str | None = None,
) -> int:
    """Store the price log of each game the service knows; return how many."""
    fetched_at = now or datetime.now(UTC).strftime(STAMP)
    since = (datetime.strptime(fetched_at, STAMP) - timedelta(days=days)).strftime(STAMP)
    ids_path = data_dir / "state" / "price_history_ids.json"
    try:
        ids = json.loads(ids_path.read_text())
    except (OSError, ValueError):
        ids = {}
    done = 0
    try:
        for game in games:
            try:
                if str(game.appid) not in ids:
                    found = _get(client, key, "/games/lookup/v1", {"appid": game.appid})
                    time.sleep(pause)
                    if not (isinstance(found, dict) and found.get("found") and found.get("game", {}).get("id")):
                        log.info("price history %s: not known to the service", game.appid)
                        continue
                    ids[str(game.appid)] = found["game"]["id"]
                changes = _get(client, key, "/games/history/v2", {
                    "id": ids[str(game.appid)], "country": "US", "shops": STEAM_SHOP, "since": since,
                })
                time.sleep(pause)
            except ItadError as exc:
                log.warning("price history %s: %s", game.appid, exc)
                if exc.fatal:
                    break
                continue
            rows = _rows(changes, game.appid, fetched_at, since)
            if rows:
                _write(data_dir / "raw" / "price_history" / f"{game.appid}.jsonl", rows)
                done += 1
    finally:
        if ids:
            ids_path.parent.mkdir(parents=True, exist_ok=True)
            ids_path.write_text(json.dumps(ids, indent=1))
    log.info("price history: %d/%d games", done, len(games))
    return done
