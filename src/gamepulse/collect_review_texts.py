"""Collect user reviews: text, verdict, language, playtime, purchase type.

Reviews are walked newest first. The first run goes back ``days`` days;
later runs fetch what is new. Every page is stored before the next one is
asked for and the position is written to ``data/state/review_texts``, so a
run that stops (page limit, Steam refusing, power cut) is continued by the
next one without leaving a hole.

Who wrote a review is not stored: no Steam id, name, profile, avatar or
location. The analysis needs what was said and by what kind of player
(playtime, language), not by whom.
"""

import json
import logging
import os
import time
from pathlib import Path

import httpx

from gamepulse.config import Game
from gamepulse.steam import SteamError, fetch_reviews_page
from gamepulse.storage import append_jsonl, read_jsonl, utc_now_iso

log = logging.getLogger(__name__)

REVIEW_FIELDS = (
    "recommendationid", "language", "review", "timestamp_created", "timestamp_updated", "voted_up",
    "votes_up", "votes_funny", "comment_count", "steam_purchase", "received_for_free",
    "written_during_early_access", "primarily_steam_deck", "refunded",
)
# Facts about the reviewer's relation to the game, not about who they are.
AUTHOR_FIELDS = {
    "playtime_at_review": "playtime_at_review",
    "playtime_forever": "playtime_forever",
    "playtime_last_two_weeks": "playtime_last_two_weeks",
    "last_played": "last_played",
    "num_reviews": "author_num_reviews",
    "num_games_owned": "author_num_games_owned",
}


def strip_review(raw: dict, appid: int, fetched_at: str) -> dict:
    """Keep the listed fields only; anything else Steam sends is dropped."""
    row = {"appid": appid, "fetched_at": fetched_at}
    row.update({key: raw.get(key) for key in REVIEW_FIELDS})
    author = raw.get("author") if isinstance(raw.get("author"), dict) else {}
    row.update({name: author.get(key) for key, name in AUTHOR_FIELDS.items()})
    try:
        row["weighted_vote_score"] = float(raw.get("weighted_vote_score"))
    except (TypeError, ValueError):
        row["weighted_vote_score"] = None
    return row


class _Budget:
    def __init__(self, pages: int):
        self.total = pages
        self.left = pages


def _read_state(path: Path) -> dict:
    try:
        state = json.loads(path.read_text())
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    os.replace(tmp, path)


def _walk(client, game, path, seen, cursor, stop_ts, budget, pause, on_page) -> str:
    """Fetch pages from ``cursor`` until a review as old as ``stop_ts``.

    ``on_page(newest_ts, oldest_ts, next_cursor)`` runs after each stored
    page. Returns "reached" (got to stop_ts), "end" (no older reviews
    exist) or "budget" (page limit used up).
    """
    while True:
        if budget.left <= 0:
            return "budget"
        if budget.left != budget.total and pause:
            time.sleep(pause)
        budget.left -= 1
        reviews, following = fetch_reviews_page(client, game.appid, cursor)
        stamps = [r["timestamp_created"] for r in reviews if isinstance(r.get("timestamp_created"), int)]
        fetched_at = utc_now_iso()
        fresh = [r for r in reviews if r.get("recommendationid") and r["recommendationid"] not in seen]
        if fresh:
            append_jsonl(path, [strip_review(r, game.appid, fetched_at) for r in fresh])
            seen.update(r["recommendationid"] for r in fresh)
        if stamps:
            on_page(max(stamps), min(stamps), following)
        if stamps and stop_ts is not None and min(stamps) <= stop_ts:
            return "reached"
        if following is None:
            return "end"
        cursor = following


def _collect_game(client, game, data_dir, floor_ts, budget, pause) -> None:
    path = data_dir / "raw" / "reviews" / f"{game.appid}.jsonl"
    state_path = data_dir / "state" / "review_texts" / f"{game.appid}.json"
    state = _read_state(state_path)
    seen = {row.get("recommendationid") for row in read_jsonl(path)}

    def save(**changes):
        state.update(changes)
        _write_state(state_path, state)

    def deepen(cursor):
        """Walk towards older reviews, moving the bottom of what is stored."""
        def on_page(newest, oldest, following):
            save(newest_ts=max(newest, state.get("newest_ts") or 0), bottom_cursor=following, bottom_ts=oldest)

        if _walk(client, game, path, seen, cursor, floor_ts, budget, pause, on_page) == "end":
            save(exhausted=True)

    if state.get("newest_ts") is None:
        deepen("*")  # first run: straight down from the newest review
        return

    def catch_up(cursor, stop_ts):
        """Walk from newer reviews down to the ones stored before. Until it
        gets there the position is kept, so a stop here leaves no hole."""
        def on_page(newest, oldest, following):
            save(newest_ts=max(newest, state["newest_ts"]), catchup_cursor=following, catchup_stop_ts=stop_ts)

        if _walk(client, game, path, seen, cursor, stop_ts, budget, pause, on_page) != "budget":
            save(catchup_cursor=None, catchup_stop_ts=None)
            return True
        return False

    if state.get("catchup_cursor") and not catch_up(state["catchup_cursor"], state.get("catchup_stop_ts")):
        return
    if not catch_up("*", state["newest_ts"]):
        return
    if not state.get("exhausted") and state.get("bottom_cursor") and (state.get("bottom_ts") or 0) > floor_ts:
        deepen(state["bottom_cursor"])


def run(
    client: httpx.Client,
    games: list[Game],
    data_dir: Path,
    *,
    days: int = 30,
    max_pages: int = 300,
    pause: float = 1.0,
    now: int | None = None,
) -> int:
    """Collect reviews of every game; return how many games had no error.

    ``max_pages`` (100 reviews each) is per game and run; what does not fit
    is continued by the next run.
    """
    floor_ts = (now if now is not None else int(time.time())) - days * 86400
    succeeded = 0
    for game in games:
        budget = _Budget(max_pages)
        try:
            _collect_game(client, game, data_dir, floor_ts, budget, pause)
        except SteamError as exc:
            log.warning("review-texts %s (%s): %s", game.appid, game.name, exc)
            continue
        except Exception:
            log.exception("review-texts %s (%s): unexpected error", game.appid, game.name)
            continue
        log.info("review-texts %s (%s): %d pages", game.appid, game.name, max_pages - budget.left)
        succeeded += 1
    log.info("review-texts: %d/%d games ok", succeeded, len(games))
    return succeeded
