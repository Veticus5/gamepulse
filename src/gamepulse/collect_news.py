"""Collect Steam news for every tracked game, with history."""

import json
import logging
import os
import time
from pathlib import Path

import httpx

from gamepulse.config import Game
from gamepulse.steam import FetchError, fetch_news_page
from gamepulse.storage import append_jsonl, read_jsonl, utc_now_iso

log = logging.getLogger(__name__)

MAX_PAGES_PER_WALK = 500


def _read_resume_point(state_path: Path) -> int | None:
    try:
        value = json.loads(state_path.read_text()).get("resume_enddate")
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, int) else None


def _write_resume_point(state_path: Path, enddate: int) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"resume_enddate": enddate, "updated_at": utc_now_iso()}))
    os.replace(tmp, state_path)


def _walk(
    client: httpx.Client,
    game: Game,
    path: Path,
    state_path: Path,
    seen: set,
    *,
    start: int | None,
    stop_when_caught_up: bool,
    pause: float,
    page_size: int,
) -> int:
    """Walk the news backwards from ``start`` (None = now); return items saved.

    Before every request after the first, the position is written to
    ``state_path``. If the walk dies there, the next run picks it up, so an
    interruption cannot leave a hole between new and old items.
    """
    saved = 0
    enddate = start
    for _ in range(MAX_PAGES_PER_WALK):
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
        if not new and stop_when_caught_up:
            break
        dates = [
            d
            for d in (item.get("date") for item in page)
            if isinstance(d, int) and not isinstance(d, bool)
        ]
        if not dates:
            raise FetchError("news page without usable dates; cannot page further back")
        oldest = min(dates)
        # `enddate` is inclusive, so a page may not move back in time at all;
        # always step at least one second to guarantee the walk ends.
        enddate = oldest if enddate is None or oldest < enddate else enddate - 1
        _write_resume_point(state_path, enddate)
        if pause:
            time.sleep(pause)
    else:
        raise FetchError(f"news walk exceeded {MAX_PAGES_PER_WALK} pages; will resume next run")
    state_path.unlink(missing_ok=True)
    return saved


def _collect_game(
    client: httpx.Client, game: Game, data_dir: Path, *, full: bool, pause: float, page_size: int
) -> int:
    path = data_dir / "raw" / "news" / f"{game.appid}.jsonl"
    state_path = data_dir / "state" / "news" / f"{game.appid}.json"
    seen = {r.get("gid") for r in read_jsonl(path)}
    common = {"pause": pause, "page_size": page_size}
    saved = 0
    resume = _read_resume_point(state_path)
    if resume is not None and not full:
        log.info("news %s (%s): resuming interrupted walk", game.appid, game.name)
        saved += _walk(
            client, game, path, state_path, seen, start=resume, stop_when_caught_up=True, **common
        )
    saved += _walk(
        client, game, path, state_path, seen, start=None, stop_when_caught_up=not full, **common
    )
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

    By default a walk stops at the first page with nothing new, so a game
    with no stored news gets its whole history. ``full`` walks the whole
    history regardless, which also picks up items added with an old date.
    """
    succeeded = 0
    total = 0
    for index, game in enumerate(games):
        if index and pause:
            time.sleep(pause)
        try:
            saved = _collect_game(
                client, game, data_dir, full=full, pause=pause, page_size=page_size
            )
        except FetchError as exc:
            log.warning("news %s (%s): %s", game.appid, game.name, exc)
            continue
        except Exception:
            log.exception("news %s (%s): unexpected error", game.appid, game.name)
            continue
        succeeded += 1
        total += saved
        if saved:
            log.info("news %s (%s): %d new", game.appid, game.name, saved)
    log.info("news: %d/%d games ok, %d new items", succeeded, len(games), total)
    return succeeded
