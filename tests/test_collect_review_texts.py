import httpx

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
