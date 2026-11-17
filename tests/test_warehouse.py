"""The staging, intermediate and mart models, built for real on small inputs."""

import datetime as dt
import json

import duckdb
import pytest

from gamepulse import model
from gamepulse.config import Game


def write(path, rows, torn=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows) + torn)


def ts(day: str) -> int:
    return int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc).timestamp())


def histogram(appid):
    # Twelve steady months and a finished day, enough for the review models to run.
    months = [f"2025-{m:02d}-01" for m in range(1, 13)]
    rollups = [{"date": ts(day), "recommendations_up": 900, "recommendations_down": 100} for day in months]
    recent = [{"date": ts("2026-11-15"), "recommendations_up": 80, "recommendations_down": 20}]
    return {"fetched_at": "2026-11-17T12:00:00Z", "appid": appid,
            "results": {"rollup_type": "month", "rollups": rollups, "recent": recent}}


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    raw, derived = data / "raw", data / "derived"
    write(raw / "review_histogram" / "730.jsonl", [histogram(730)])

    def count(when, players, appid=730, ok=True):
        return {"ts": when, "appid": appid, "player_count": players, "ok": ok, "error": None if ok else "HTTP 500"}

    write(raw / "ccu" / "2026-11-16.jsonl", [
        count("2026-11-16T10:00:00Z", 100), count("2026-11-16T10:30:00Z", 300),
        count("2026-11-16T11:00:00Z", None, ok=False),  # a failed read is not a measurement
        count("2026-11-16T10:00:00Z", 7, appid=570),
    ], torn='{"ts": "2026-11-16T11:3')  # the collector was writing
    write(raw / "ccu" / "gh-2026-11-16.jsonl", [
        count("2026-11-16T10:30:00Z", 300),  # the same moment as the local file: kept once
        count("2026-11-17T09:00:00Z", 200),
    ])
    write(raw / "fivem" / "2026-11-16.jsonl", [
        {"ts": "2026-11-16T10:00:00Z", "url": "https://example.test/counts.json", "counts": [5, 0, 9], "ok": True, "error": None},
    ])

    def price(when, percent, final):
        return {"ts": when, "appid": 730, "priced": True, "currency": "USD", "initial": 2000, "final": final, "discount_percent": percent}

    write(raw / "prices" / "2026-11-16.jsonl", [price("2026-11-16T10:00:00Z", 0, 2000), price("2026-11-16T22:00:00Z", 25, 1500)])

    def change(when, percent, final):
        return {"fetched_at": "2026-11-17T10:00:00Z", "since": "2025-10-13T10:00:00Z", "appid": 730,
                "ts": when, "currency": "USD", "initial": 2000, "final": final, "discount_percent": percent}

    write(raw / "price_history" / "730.jsonl", [
        change("2025-11-20T18:00:00Z", 50, 1000), change("2025-11-22T18:00:00Z", 0, 2000), change("2026-11-15T18:00:00Z", 10, 1800),
    ])

    def post(gid, title, feed_type=1, fetched="2026-11-16T10:00:00Z"):
        return {"gid": gid, "appid": 730, "title": title, "url": f"https://example.test/{gid}", "author": "dev",
                "contents": "text", "feedlabel": "Announcements", "feedname": "steam", "feed_type": feed_type,
                "date": ts("2026-11-10"), "tags": ["patchnotes"], "fetched_at": fetched}

    write(raw / "news" / "730.jsonl", [
        post("1", "Old title"), post("1", "New title", fetched="2026-11-17T10:00:00Z"), post("2", "Press piece", feed_type=0),
    ])

    def label(event_type, when):
        return {"gid": "1", "appid": 730, "event_type": event_type, "effective_date": "2026-11-11", "summary": "s",
                "importance": "high", "confidence": 0.9, "model": "m", "prompt_version": "v1", "classified_at": when}

    write(derived / "news_events" / "730.jsonl", [label("patch", "2026-11-14T10:00:00Z"), label("content", "2026-11-15T10:00:00Z")])
    count_built = model.run(data, [Game(730, "Counter-Strike 2"), Game(570, "Dota 2")])
    assert count_built == 0  # steady reviews: nothing unusual
    with duckdb.connect(str(model.warehouse_path(data)), read_only=True) as con:
        yield con


def rows(db, sql):
    return db.execute(sql).fetchall()


def test_player_counts_keep_only_real_measurements_once(db):
    assert rows(db, "select appid, strftime(measured_at, '%d %H:%M'), player_count, collected_by from stg_player_counts order by 1, 2") == [
        (570, "16 10:00", 7, "local"),
        (730, "16 10:00", 100, "local"),
        (730, "16 10:30", 300, "local"),  # collected twice: the local copy is kept
        (730, "17 09:00", 200, "github"),
    ]


def test_player_counts_per_day(db):
    assert rows(db, "select strftime(day, '%m-%d'), samples, players_min, players_max, players_avg from int_player_counts_daily where appid = 730 order by 1") == [
        ("11-16", 2, 100, 300, 200), ("11-17", 1, 200, 200, 200),
    ]


def test_fivem_counts_keep_the_raw_list(db):
    assert rows(db, "select players, counts from stg_fivem_counts") == [(5, [5, 0, 9])]


def test_daily_prices_merge_own_readings_with_the_price_log(db):
    found = dict(rows(db, "select strftime(day, '%Y-%m-%d'), discount_percent from int_prices_daily where appid = 730 and discount_percent > 0"))
    # The old sale runs up to and including the day it ended; the last known
    # price holds until the log was fetched; on 16 November our own reading wins.
    assert found == {
        "2025-11-20": 50, "2025-11-21": 50, "2025-11-22": 50,
        "2026-11-15": 10, "2026-11-16": 25, "2026-11-17": 10,
    }
    assert rows(db, "select final_price_cents, from_own_collection, from_price_log from int_prices_daily where appid = 730 and day = date '2026-11-16'") == [(1500, True, True)]
    assert rows(db, "select strftime(min(day), '%Y-%m-%d') from int_prices_daily") == [("2025-11-20",)]


def test_news_keep_the_latest_version_and_label(db):
    assert rows(db, "select gid, title, is_official, is_labelled, event_type, tags from news order by gid") == [
        ("1", "New title", True, True, "content", ["patchnotes"]),
        ("2", "Press piece", False, False, None, ["patchnotes"]),
    ]


def test_games_show_the_current_state(db):
    assert rows(db, "select appid, name, players_now, players_peak_24h, final_price_cents, discount_percent, reviews_last_day, episodes from games order by appid") == [
        (570, "Dota 2", 7, 7, None, None, None, 0),
        (730, "Counter-Strike 2", 200, 300, 1800, 10, 100, 0),
    ]


def test_sources_never_collected_give_empty_tables(db):
    # No explanations and no episodes in this data set: the tables exist and are empty.
    assert rows(db, "select count(*) from stg_explanations") == [(0,)]
    assert rows(db, "select count(*) from episode_explanations") == [(0,)]
