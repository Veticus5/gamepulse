import httpx

from gamepulse import collect_review_texts
from gamepulse import collect_review_texts as crt
from gamepulse.config import Game
from gamepulse.storage import read_jsonl

GAME = [Game(730, "Counter-Strike 2")]
NOW = 2_000_000_000
DAY = 86400


def review(number: int, ts: int) -> dict:
    return {
        "recommendationid": str(number),
        "author": {
            "steamid": "76561190000000000", "personaname": "Someone", "profile_url": "https://example.invalid/p",
            "avatar": "abc", "persona_status": "online", "num_games_owned": 12, "num_reviews": 3,
            "playtime_forever": 600, "playtime_last_two_weeks": 60, "playtime_at_review": 500, "last_played": ts,
        },
        "language": "polish", "review": f"text {number}", "timestamp_created": ts, "timestamp_updated": ts,
        "voted_up": number % 2 == 0, "votes_up": 1, "votes_funny": 0, "weighted_vote_score": "0.5",
        "comment_count": 0, "steam_purchase": True, "received_for_free": False,
        "written_during_early_access": False, "primarily_steam_deck": False, "refunded": False,
        "location": "PL", "hardware": {"gpu": "x"}, "reactions": [],
    }


class Steam:
    """A fake review feed: newest first, 3 per page, cursor = position."""

    def __init__(self, reviews):
        self.reviews = sorted(reviews, key=lambda r: -r["timestamp_created"])
        self.requests = []
        self.fail_on_request = None

    def add(self, *reviews):
        self.reviews = sorted([*self.reviews, *reviews], key=lambda r: -r["timestamp_created"])

    def handler(self, request):
        cursor = request.url.params["cursor"]
        self.requests.append(cursor)
        if self.fail_on_request == len(self.requests):
            return httpx.Response(429)
        # A cursor names the last review of the previous page, so it stays valid when new reviews arrive.
        start = 0 if cursor == "*" else next(i for i, r in enumerate(self.reviews) if r["recommendationid"] == cursor) + 1
        page = self.reviews[start:start + 3]
        return httpx.Response(200, json={
            "success": 1, "reviews": page, "cursor": page[-1]["recommendationid"] if page else cursor,
        })


def feed(count=10, step=DAY):
    """Review n was written n days ago: ids 1..count, newest = 1."""
    return Steam([review(n, NOW - n * step) for n in range(1, count + 1)])


def run(steam, client_for, tmp_path, **kwargs):
    options = {"days": 30, "max_pages": 100, "pause": 0, "now": NOW, **kwargs}
    return crt.run(client_for(steam.handler), GAME, tmp_path, **options)


def stored(tmp_path):
    return read_jsonl(tmp_path / "raw" / "reviews" / "730.jsonl")


def ids(tmp_path):
    return sorted(int(r["recommendationid"]) for r in stored(tmp_path))


def test_first_run_stores_reviews_back_to_the_floor_without_personal_data(tmp_path, client_for):
    steam = feed(10)
    assert run(steam, client_for, tmp_path, days=5) == 1
    assert ids(tmp_path) == [1, 2, 3, 4, 5, 6]  # the page that crosses the floor is kept whole
    row = stored(tmp_path)[0]
    assert row["appid"] == 730 and row["fetched_at"].endswith("Z")
    assert row["review"] == "text 1" and row["language"] == "polish" and row["voted_up"] is False
    assert (row["playtime_at_review"], row["playtime_forever"], row["author_num_reviews"]) == (500, 600, 3)
    assert row["steam_purchase"] is True and row["weighted_vote_score"] == 0.5
    text = str(row)
    for secret in ("steamid", "76561190000000000", "Someone", "profile_url", "avatar", "location", "hardware"):
        assert secret not in text


def test_next_run_fetches_only_what_is_new(tmp_path, client_for):
    steam = feed(6)
    run(steam, client_for, tmp_path)
    steam.add(review(100, NOW + 10), review(101, NOW + 20))
    steam.requests.clear()
    assert run(steam, client_for, tmp_path, now=NOW + 30) == 1
    assert steam.requests == ["*"]  # one page reaches reviews already stored
    assert ids(tmp_path) == [1, 2, 3, 4, 5, 6, 100, 101]
    run(steam, client_for, tmp_path, now=NOW + 30)
    assert len(stored(tmp_path)) == 8  # nothing stored twice


def test_page_cap_is_resumed_by_later_runs_without_gaps(tmp_path, client_for):
    steam = feed(10)
    run(steam, client_for, tmp_path, max_pages=2)
    assert ids(tmp_path) == [1, 2, 3, 4, 5, 6]
    steam.add(review(100, NOW + 10))  # arrives between the runs
    run(steam, client_for, tmp_path, max_pages=2, now=NOW + 30)
    run(steam, client_for, tmp_path, max_pages=2, now=NOW + 30)
    assert ids(tmp_path) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 100]
    assert len(stored(tmp_path)) == 11


def test_failure_mid_walk_is_resumed(tmp_path, client_for):
    steam = feed(10)
    steam.fail_on_request = 2
    assert run(steam, client_for, tmp_path) == 0
    assert ids(tmp_path) == [1, 2, 3]
    steam.fail_on_request = None
    assert run(steam, client_for, tmp_path) == 1
    assert ids(tmp_path) == list(range(1, 11))
    assert len(stored(tmp_path)) == 10


def test_failure_while_catching_up_leaves_no_hole(tmp_path, client_for):
    steam = feed(3)
    run(steam, client_for, tmp_path)
    steam.add(*[review(100 + n, NOW + n) for n in range(1, 8)])  # 7 new: three pages to catch up
    steam.requests.clear()
    steam.fail_on_request = 2
    assert run(steam, client_for, tmp_path, now=NOW + 30) == 0
    steam.fail_on_request = None
    steam.add(review(200, NOW + 20))
    assert run(steam, client_for, tmp_path, now=NOW + 30) == 1
    assert ids(tmp_path) == [1, 2, 3, 101, 102, 103, 104, 105, 106, 107, 200]


def test_longer_history_can_be_requested_later(tmp_path, client_for):
    steam = feed(10)
    run(steam, client_for, tmp_path, days=2)
    assert ids(tmp_path) == [1, 2, 3]
    run(steam, client_for, tmp_path, days=30)
    assert ids(tmp_path) == list(range(1, 11))


def test_empty_feed_is_fine(tmp_path, client_for):
    assert run(Steam([]), client_for, tmp_path) == 1
    assert stored(tmp_path) == []


# --- reviews for the stretch of an episode

def _episode_setup(monkeypatch, episodes):
    monkeypatch.setattr(collect_review_texts.warehouse, "load_episodes", lambda data_dir: episodes)


def _episode(appid, start, end):
    import datetime as dt
    return {"appid": appid, "period_start": dt.date.fromisoformat(start), "period_end": dt.date.fromisoformat(end)}


def _stamp(day):
    import datetime as dt
    return int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc).timestamp())


def _review(number, ts):
    return {"recommendationid": str(number), "timestamp_created": ts, "voted_up": True, "review": "text",
            "language": "english", "author": {"steamid": "secret", "playtime_at_review": 60}}


def test_episode_reviews_are_fetched_by_date_range(tmp_path, games, client_for, monkeypatch):
    import datetime as dt
    _episode_setup(monkeypatch, [
        _episode(730, "2026-03-01", "2026-03-08"),
        _episode(730, "2024-01-01", "2024-01-02"),  # too old to matter
        _episode(999, "2026-03-01", "2026-03-08"),  # not a tracked game
    ])
    seen = []
    pages = {"*": ([_review(1, _stamp("2026-03-07")), _review(2, _stamp("2026-03-06"))], "c2"),
             "c2": ([_review(3, _stamp("2026-03-02"))], "c3"),
             "c3": ([], "c3")}

    def handler(request):
        params = dict(request.url.params)
        seen.append(params)
        reviews, cursor = pages[params["cursor"]]
        return httpx.Response(200, json={"success": 1, "reviews": reviews, "cursor": cursor})

    done = collect_review_texts.run_episodes(client_for(handler), games, tmp_path, pause=0, today=dt.date(2026, 11, 17))
    assert done == 1
    assert [p["cursor"] for p in seen] == ["*", "c2", "c3"]
    assert {(p["start_date"], p["end_date"], p["date_range_type"]) for p in seen} == {
        (str(_stamp("2026-03-01")), str(_stamp("2026-03-08")), "include")
    }
    stored = read_jsonl(tmp_path / "raw" / "reviews" / "730.jsonl")
    assert [row["recommendationid"] for row in stored] == ["1", "2", "3"]
    assert all("steamid" not in row and "author" not in row for row in stored)  # no reviewer identity
    # A second run has nothing left to ask for.
    seen.clear()
    assert collect_review_texts.run_episodes(client_for(handler), games, tmp_path, pause=0, today=dt.date(2026, 11, 17)) == 1
    assert seen == []


def test_episode_already_reached_by_the_ordinary_walk_is_skipped(tmp_path, games, client_for, monkeypatch):
    import datetime as dt
    import json
    _episode_setup(monkeypatch, [_episode(730, "2026-11-01", "2026-11-03")])
    state = tmp_path / "state" / "review_texts" / "730.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"bottom_ts": _stamp("2026-10-15")}))

    def handler(request):
        raise AssertionError("no request expected")

    assert collect_review_texts.run_episodes(client_for(handler), games, tmp_path, pause=0, today=dt.date(2026, 11, 17)) == 1


def test_interrupted_episode_resumes_from_its_cursor(tmp_path, games, client_for, monkeypatch):
    import datetime as dt
    _episode_setup(monkeypatch, [_episode(730, "2026-03-01", "2026-03-08")])
    calls = []

    def flaky(request):
        cursor = request.url.params["cursor"]
        calls.append(cursor)
        if cursor == "*":
            return httpx.Response(200, json={"success": 1, "reviews": [_review(1, _stamp("2026-03-07"))], "cursor": "c2"})
        return httpx.Response(200, json={"success": 1})  # Steam stops answering

    assert collect_review_texts.run_episodes(client_for(flaky), games, tmp_path, pause=0, today=dt.date(2026, 11, 17)) == 0

    def healthy(request):
        cursor = request.url.params["cursor"]
        calls.append(cursor)
        if cursor == "c2":
            return httpx.Response(200, json={"success": 1, "reviews": [_review(2, _stamp("2026-03-02"))], "cursor": "c3"})
        return httpx.Response(200, json={"success": 1, "reviews": [], "cursor": cursor})

    assert collect_review_texts.run_episodes(client_for(healthy), games, tmp_path, pause=0, today=dt.date(2026, 11, 17)) == 1
    assert calls == ["*", "c2", "c2", "c3"]  # resumed at c2, not from the top
    assert [r["recommendationid"] for r in read_jsonl(tmp_path / "raw" / "reviews" / "730.jsonl")] == ["1", "2"]
