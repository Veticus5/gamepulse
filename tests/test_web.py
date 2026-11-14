import time

import pytest
from fastapi.testclient import TestClient

from gamepulse.config import Game
from gamepulse.storage import append_jsonl
from gamepulse.web.app import create_app
from gamepulse.web.store import DAY, HOUR, MINUTE, Store

GAMES = [Game(730, "Counter-Strike 2"), Game(570, "Dota 2"), Game(413150, "Stardew Valley")]
NOW = 1_794_680_000_000  # ms, a fixed "now" for the fixtures


def iso(ms):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ms / 1000))


def ccu_row(ms, appid, players, ok=True):
    return {"ts": iso(ms), "appid": appid, "player_count": players if ok else None, "ok": ok, "error": None}


@pytest.fixture
def data_dir(tmp_path):
    raw = tmp_path / "raw"
    rows = []
    for step in range(0, 25 * 12):  # 25 hours, every 5 minutes, newest last
        ms = NOW - (25 * 12 - 1 - step) * 5 * MINUTE
        if 100 <= step < 112:
            continue  # one hour with the computer off
        rows.append(ccu_row(ms, 730, 1000 + step))
        rows.append(ccu_row(ms, 570, 5000))
    rows.append(ccu_row(NOW, 413150, None, ok=False))
    append_jsonl(raw / "ccu" / "2026-11-14.jsonl", rows)
    append_jsonl(
        raw / "news" / "730.jsonl",
        [
            {"gid": "a", "appid": 730, "title": "Patch", "date": (NOW - 2 * DAY) // 1000, "feed_type": 1,
             "feedlabel": "Community Announcements", "url": "https://example.invalid/a", "contents": "notes more"},
            {"gid": "b", "appid": 730, "title": "Press", "date": (NOW - 1 * DAY) // 1000, "feed_type": 0,
             "feedlabel": "PC Gamer", "url": "https://example.invalid/b", "contents": "<b>x</b>"},
            {"gid": "old", "appid": 730, "title": "Old", "date": (NOW - 400 * DAY) // 1000, "feed_type": 1,
             "feedlabel": "Community Announcements", "url": "https://example.invalid/o", "contents": ""},
        ],
    )
    append_jsonl(
        raw / "review_histogram" / "730.jsonl",
        [
            {"fetched_at": "x", "appid": 730, "results": {"rollups": [], "recent": []}},
            {"fetched_at": "y", "appid": 730, "results": {
                "rollups": [{"date": (NOW - 400 * DAY) // 1000, "recommendations_up": 90, "recommendations_down": 10}],
                "recent": [{"date": (NOW - 3 * DAY) // 1000, "recommendations_up": 3, "recommendations_down": 1}],
            }},
        ],
    )
    append_jsonl(
        raw / "appdetails" / "730.jsonl",
        [{"fetched_at": "x", "appid": 730, "details": {
            "developers": ["Valve"], "release_date": {"date": "Aug 21, 2012"},
            "genres": [{"description": "Action"}], "header_image": "https://example.invalid/h.jpg"}}],
    )
    append_jsonl(
        raw / "fivem" / "2026-11-14.jsonl",
        [
            {"ts": iso(NOW), "url": "https://static.cfx.re/runtime/counts.json", "counts": [257625, 0, 257625], "ok": True},
            {"ts": iso(NOW), "url": "https://runtime.fivem.net/counts.json", "counts": [None, 297210, None], "ok": True},
        ],
    )
    return tmp_path


def test_overview_sorts_by_players_and_puts_missing_last(data_dir):
    games = Store(data_dir, GAMES).overview()["games"]
    assert [g["appid"] for g in games] == [570, 730, 413150]
    assert games[0]["players"] == 5000
    assert games[2]["players"] is None


def test_overview_change_sparkline_reviews_and_news(data_dir):
    cs = next(g for g in Store(data_dir, GAMES).overview()["games"] if g["appid"] == 730)
    assert cs["players"] == 1299
    assert cs["players_ts"] == NOW - NOW % 1000
    assert cs["change_24h"] == pytest.approx(100 * 288 / 1011, abs=0.1)
    assert 40 <= len(cs["spark"]) <= 49
    assert cs["reviews"]["recent"] == {"up": 3, "down": 1, "pct": 75.0}
    assert cs["reviews"]["all"]["pct"] == 90.0
    assert cs["last_news"]["title"] == "Patch"  # newest official, not the newer press item
    assert cs["developers"] == ["Valve"]
    assert cs["image"] == "https://example.invalid/h.jpg"


def test_overview_status_counts_gaps_and_fivem(data_dir):
    result = Store(data_dir, GAMES).overview()
    assert result["status"]["gaps_24h"] == 1
    assert result["status"]["last_ts"] == NOW - NOW % 1000
    assert result["fivem"]["players"] == 257625


def test_game_range_never_starts_before_first_measurement(data_dir):
    store = Store(data_dir, GAMES)
    first = NOW - (25 * 12 - 1) * 5 * MINUTE
    first -= first % 1000
    for key in ("7d", "30d", "all"):
        result = store.game(730, key, NOW)
        assert result["range"]["from"] == first
        assert result["ccu_first_ts"] == first
    assert store.game(730, "24h", NOW)["range"]["from"] == NOW - DAY


def test_game_24h_returns_raw_points_and_peak(data_dir):
    day = Store(data_dir, GAMES).game(730, "24h", NOW)
    assert day["ccu_bucket_ms"] is None
    assert day["ccu"][-1] == [NOW - NOW % 1000, 1299]
    assert all(a[0] < b[0] for a, b in zip(day["ccu"], day["ccu"][1:]))
    assert day["peak_24h"] == 1299


def test_game_markers_one_per_day_official_only(data_dir):
    append_jsonl(
        data_dir / "raw" / "news" / "730.jsonl",
        [
            {"gid": "m1", "appid": 730, "title": "Fan Art Winners", "date": (NOW - 3 * HOUR) // 1000, "feed_type": 1},
            {"gid": "m2", "appid": 730, "title": "Season 5 is Now Available", "date": (NOW - 2 * HOUR) // 1000, "feed_type": 1},
            {"gid": "m3", "appid": 730, "title": "Press piece", "date": (NOW - 1 * HOUR) // 1000, "feed_type": 0},
        ],
    )
    result = Store(data_dir, GAMES).game(730, "24h", NOW)
    assert len(result["markers"]) == 1
    marker = result["markers"][0]
    assert marker["count"] == 2
    assert marker["priority"] == 3
    assert [i["gid"] for i in marker["items"]] == ["m2", "m1"]
    assert marker["at_ms"] == (NOW - 2 * HOUR) // 1000 * 1000


def test_game_highlights_prefer_important_recent_official_news(data_dir):
    rows = [
        {"gid": f"c{i}", "appid": 730, "title": f"Fan Art Showcase #{i}", "date": (NOW - i * DAY) // 1000, "feed_type": 1}
        for i in range(1, 9)
    ]
    rows.append({"gid": "big", "appid": 730, "title": "Operation X is Now Available", "date": (NOW - 60 * DAY) // 1000, "feed_type": 1})
    rows.append({"gid": "ancient", "appid": 730, "title": "Old Launch is Now Available", "date": (NOW - 200 * DAY) // 1000, "feed_type": 1})
    append_jsonl(data_dir / "raw" / "news" / "730.jsonl", rows)
    result = Store(data_dir, GAMES).game(730, "7d", NOW)
    gids = [h["gid"] for h in result["highlights"]]
    assert len(gids) == 5
    assert "big" in gids and "a" in gids  # the launch and the patch beat fan art
    assert "ancient" not in gids and "b" not in gids  # too old; not from the developer
    assert gids == sorted(gids, key=lambda g: -next(h["date_ms"] for h in result["highlights"] if h["gid"] == g))
    assert result["news_totals"] == {"official": 12, "external": 1, "classified": 0}


def test_review_markers_launches_per_month_and_notable_per_day(data_dir):
    append_jsonl(
        data_dir / "raw" / "news" / "730.jsonl",
        [
            {"gid": "l1", "appid": 730, "title": "Operation A is Now Available", "date": (NOW - 400 * DAY) // 1000, "feed_type": 1},
            {"gid": "l2", "appid": 730, "title": "Operation B is Now Available", "date": (NOW - 400 * DAY + HOUR) // 1000, "feed_type": 1},
            {"gid": "f1", "appid": 730, "title": "Fan Art Winners", "date": (NOW - 5 * DAY) // 1000, "feed_type": 1},
        ],
    )
    markers = Store(data_dir, GAMES).game(730, "7d", NOW)["review_markers"]
    assert [(m["count"], m["priority"]) for m in markers["monthly"]] == [(2, 3)]
    assert [m["items"][0]["gid"] for m in markers["daily"]] == ["a"]  # the patch; fan art is not notable


def test_game_reviews_carry_both_granularities(data_dir):
    reviews = Store(data_dir, GAMES).game(730, "7d", NOW)["reviews"]
    assert reviews["daily"] == [[(NOW - 3 * DAY) // 1000 * 1000, 3, 1]]
    assert reviews["monthly"] == [[(NOW - 400 * DAY) // 1000 * 1000, 90, 10]]


def test_news_list_filters_searches_and_pages(data_dir):
    store = Store(data_dir, GAMES)
    assert [n["gid"] for n in store.news_list(730, "official", "", 0, 50)["items"]] == ["a", "old"]
    assert [n["gid"] for n in store.news_list(730, "external", "", 0, 50)["items"]] == ["b"]
    everything = store.news_list(730, "all", "", 0, 2)
    assert everything["total"] == 3 and [n["gid"] for n in everything["items"]] == ["b", "a"]
    assert [n["gid"] for n in store.news_list(730, "all", "", 2, 2)["items"]] == ["old"]
    assert [n["gid"] for n in store.news_list(730, "all", "PAT", 0, 50)["items"]] == ["a"]
    assert store.news_list(730, "all", "%", 0, 50)["total"] == 0  # a literal percent sign, not a wildcard
    assert store.news_list(730, "bogus", "", 0, 50) is None
    assert store.news_list(1, "all", "", 0, 50) is None


def test_store_picks_up_new_measurements(data_dir):
    store = Store(data_dir, GAMES)
    store.overview()
    append_jsonl(data_dir / "raw" / "ccu" / "2026-11-15.jsonl", [ccu_row(NOW + 5 * MINUTE, 730, 7777)])
    cs = next(g for g in store.overview()["games"] if g["appid"] == 730)
    assert cs["players"] == 7777


def test_empty_data_dir_works(tmp_path):
    store = Store(tmp_path, GAMES)
    result = store.overview()
    assert [g["players"] for g in result["games"]] == [None, None, None]
    assert result["status"]["last_ts"] is None
    assert result["fivem"]["players"] is None
    assert store.game(730, "30d", NOW)["ccu"] == []


def test_api_endpoints(data_dir):
    client = TestClient(create_app(data_dir, GAMES))
    assert client.get("/api/overview").json()["games"][0]["appid"] == 570
    assert client.get("/api/games/730?range=7d").status_code == 200
    assert client.get("/api/games/730?range=bogus").status_code == 400
    assert client.get("/api/games/1").status_code == 404
    item = client.get("/api/games/730/news/a").json()
    assert item["contents"] == "notes more"
    assert item["category"] == "patch"
    assert client.get("/api/games/730/news?kind=all&q=press").json()["total"] == 1
    assert client.get("/api/games/730/news?kind=bogus").status_code == 400
    assert client.get("/api/games/730/news?limit=9999").status_code == 422
    assert client.get("/api/games/730/news/zzz").status_code == 404
    assert client.get("/api/games/570/news/a").status_code == 404
    assert client.get("/").status_code == 200


def test_model_labels_replace_rules_and_move_markers_to_the_effective_date(data_dir):
    from datetime import UTC, datetime

    effective = datetime.fromtimestamp((NOW - 6 * HOUR) / 1000, UTC).date().isoformat()
    append_jsonl(
        data_dir / "derived" / "news_events" / "730.jsonl",
        [
            {"gid": "a", "appid": 730, "event_type": "community", "importance": "low", "summary": "stare", "effective_date": None},
            {"gid": "a", "appid": 730, "event_type": "content_release", "importance": "high",
             "summary": "Nowa operacja.", "effective_date": effective, "secondary_types": ["sale"]},
            {"gid": "b", "appid": 730, "event_type": "patch", "importance": "high", "summary": "x", "effective_date": None},
        ],
    )
    store = Store(data_dir, GAMES)
    item = store.news_item(730, "a")
    assert (item["category"], item["priority"], item["source"]) == ("content_release", 3, "model")
    assert item["summary"] == "Nowa operacja." and item["effective_date"] == effective
    assert item["secondary"] == ["sale"] and store.news_item(730, "old")["secondary"] == []
    assert store.news_item(730, "b")["source"] == "rules"  # not from the developer: labels are ignored
    assert store.news_item(730, "old")["source"] == "rules"
    result = store.game(730, "24h", NOW)
    # Published two days ago, but takes effect within the last 24 hours.
    assert [m["items"][0]["gid"] for m in result["markers"]] == ["a"]
    assert result["news_totals"]["classified"] == 1
