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


def test_game_range_filters_news_and_picks_review_granularity(data_dir):
    store = Store(data_dir, GAMES)
    month = store.game(730, "30d", NOW)
    assert [n["gid"] for n in month["news"]] == ["b", "a"]
    assert month["news"][1]["official"] is True and month["news"][0]["official"] is False
    assert month["reviews"]["granularity"] == "day"
    assert month["reviews"]["points"] == [[(NOW - 3 * DAY) // 1000 * 1000, 3, 1]]
    assert month["ccu_bucket_ms"] == HOUR
    everything = store.game(730, "all", NOW)
    assert [n["gid"] for n in everything["news"]] == ["b", "a", "old"]
    assert everything["reviews"]["granularity"] == "month"
    assert len(everything["reviews"]["points"]) == 1


def test_game_24h_returns_raw_points(data_dir):
    day = Store(data_dir, GAMES).game(730, "24h", NOW)
    assert day["ccu_bucket_ms"] is None
    assert day["ccu"][-1] == [NOW - NOW % 1000, 1299]
    assert all(a[0] < b[0] for a, b in zip(day["ccu"], day["ccu"][1:]))


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
    assert client.get("/api/games/730/news/zzz").status_code == 404
    assert client.get("/api/games/570/news/a").status_code == 404
    assert client.get("/").status_code == 200
