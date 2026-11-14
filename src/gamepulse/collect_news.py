"""Collect Steam news for every tracked game, with history."""

import logging
import time
from pathlib import Path

import httpx

from gamepulse.config import Game
from gamepulse.steam import SteamError, fetch_news_page
from gamepulse.storage import append_jsonl, read_jsonl, utc_now_iso

log = logging.getLogger(__name__)


def _collect_game(
    client: httpx.Client, game: Game, path: Path, *, full: bool, pause: float, page_size: int
) -> int:
    """Walk the news backwards from now; return the number of new items saved."""
    seen = {r.get("gid") for r in read_jsonl(path)}
    saved = 0
    enddate: int | None = None
    while True:
        page = fetch_news_page(client, game.appid, count=page_size, enddate=enddate)
        if not page:
            break
        fetched_at = utc_now_iso()
        new = []
        for item in page:
            gid = item.get("gid")
            if gid is None or gid in seen:
                continue
            seen.add(gid)
            new.append({**item, "fetched_at": fetched_at})
        # Saved page by page, so an interrupted backfill keeps what it got.
        saved += append_jsonl(path, new)
        if not new and not full:
            break  # caught up with what is already stored
        dates = [d for d in (item.get("date") for item in page) if isinstance(d, int)]
        if not dates:
            break
        oldest = min(dates)
        # `enddate` is inclusive, so a page may not move back in time at all;
        # always step at least one second to guarantee the walk ends.
        enddate = oldest if enddate is None or oldest < enddate else enddate - 1
        if pause:
            time.sleep(pause)
    return saved


def run(
    client: httpx.Client,
    games: list[Game],
    data_dir: Path,
    *,
    full: bool = False,
    pause: float = 0.2,
    page_size: int = 100,
) -> int:
    """Append unseen news per game; return how many games succeeded.

    By default the walk stops at the first page with nothing new. ``full``
    walks the whole history, which also completes an interrupted backfill.
    """
    succeeded = 0
    total = 0
    for game in games:
        path = data_dir / "raw" / "news" / f"{game.appid}.jsonl"
        try:
            saved = _collect_game(
                client, game, path, full=full, pause=pause, page_size=page_size
            )
        except SteamError as exc:
            log.warning("news %s (%s): %s", game.appid, game.name, exc)
            continue
        succeeded += 1
        total += saved
        if saved:
            log.info("news %s (%s): %d new", game.appid, game.name, saved)
    log.info("news: %d/%d games ok, %d new items", succeeded, len(games), total)
    return succeeded
