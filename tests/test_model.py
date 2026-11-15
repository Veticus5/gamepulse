"""The dbt models run for real here, on small made-up review histories."""

import datetime as dt
import json

import pytest

from gamepulse import model

FETCHED = "2026-11-14T12:00:00Z"


def ts(day: str) -> int:
    return int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc).timestamp())


def months(start_year: int, start_month: int, count: int) -> list[str]:
    out = []
    year, month = start_year, start_month
    for _ in range(count):
        out.append(f"{year:04d}-{month:02d}-01")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return out


def row(day: str, up: int, down: int) -> dict:
    return {"date": ts(day), "recommendations_up": up, "recommendations_down": down}


def snapshot(appid: int, *, rollups=(), recent=(), rollup_type="month", fetched_at=FETCHED) -> dict:
    return {
        "fetched_at": fetched_at,
        "appid": appid,
        "results": {"rollup_type": rollup_type, "rollups": list(rollups), "recent": list(recent)},
    }


def steady(days: list[str], up: int = 900, down: int = 100) -> list[dict]:
    # A little wobble so the spread of the baseline is not exactly zero.
    return [row(day, up + (i % 3) * 5, down - (i % 3) * 5) for i, day in enumerate(days)]


@pytest.fixture(scope="module")
def anomalies(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("data")
    raw = data_dir / "raw" / "review_histogram"
    raw.mkdir(parents=True)
    year = months(2025, 1, 12)  # Jan..Dec 2025

    def write(appid: int, *snapshots: dict) -> None:
        (raw / f"{appid}.jsonl").write_text("".join(json.dumps(s) + "\n" for s in snapshots))

    # 1: score collapses in January 2026, back to normal afterwards.
    write(1, snapshot(1, rollups=steady(year) + [row("2026-01-01", 600, 400), row("2026-02-01", 900, 100)]))
    # 2: five times the usual number of reviews, same score.
    write(2, snapshot(2, rollups=steady(year) + [row("2026-01-01", 4500, 500)]))
    # 3: too few reviews to say anything, however bad the score looks.
    write(3, snapshot(3, rollups=steady(year, 18, 2) + [row("2026-01-01", 10, 10)]))
    # 4: the running month (November 2026) is not finished, so it is not judged.
    write(4, snapshot(4, rollups=steady(months(2025, 11, 12)) + [row("2026-11-01", 60, 40)]))
    # 5: a bad month, but only five earlier months to compare with.
    write(5, snapshot(5, rollups=steady(months(2025, 1, 5)) + [row("2025-06-01", 600, 400)]))
    # 6: weekly rollups; score jumps up in the last finished week.
    weeks = [(dt.date(2026, 6, 1) + dt.timedelta(weeks=i)).isoformat() for i in range(12)]
    write(6, snapshot(6, rollup_type="week", rollups=steady(weeks, 600, 400) + [row("2026-08-24", 950, 50)]))
    # 7: daily data; a later snapshot corrects the same day, and the later one counts.
    days = [(dt.date(2026, 10, 20) + dt.timedelta(days=i)).isoformat() for i in range(14)]
    write(
        7,
        snapshot(7, recent=steady(days) + [row("2026-11-03", 900, 100)], fetched_at="2026-11-04T12:00:00Z"),
        snapshot(7, recent=[row("2026-11-03", 500, 500)], fetched_at="2026-11-05T12:00:00Z"),
    )
    # 8: a torn last line (collector was writing) must not break the run.
    (raw / "8.jsonl").write_text(json.dumps(snapshot(8, rollups=steady(year))) + '\n{"fetched_at": "2026-')

    # 9: three bad months in a row are one episode; a later bad month with a
    # flood of reviews is another.
    write(9, snapshot(9, rollups=steady(year) + [
        row("2026-01-01", 600, 400), row("2026-02-01", 600, 400), row("2026-03-01", 600, 400),
        row("2026-04-01", 900, 100), row("2026-05-01", 900, 100), row("2026-06-01", 3000, 2000),
        row("2026-07-01", 900, 100),
    ]))

    count = model.run(data_dir)
    rows = model.load_anomalies(data_dir)
    assert count == len(rows)
    return data_dir, rows


def pick(rows, appid):
    return [r for r in rows if r["appid"] == appid]


def test_score_drop_is_found(anomalies):
    _, rows = anomalies
    found = pick(rows, 1)
    assert [(r["kind"], r["grain"], str(r["period_start"])) for r in found] == [
        ("review_score_drop", "month", "2026-01-01")
    ]
    hit = found[0]
    assert hit["value"] == pytest.approx(0.6)
    assert hit["baseline"] == pytest.approx(0.905, abs=0.01)
    assert hit["reviews"] == 1000
    assert hit["baseline_periods"] == 12
    assert hit["score"] < -3.5
    assert str(hit["period_end"]) == "2026-02-01"


def test_volume_spike_is_found(anomalies):
    _, rows = anomalies
    found = pick(rows, 2)
    assert [r["kind"] for r in found] == ["review_volume_spike"]
    assert found[0]["value"] == 5000
    assert found[0]["baseline"] == pytest.approx(1000)
    assert found[0]["deviation"] == pytest.approx(5.0)


def test_small_samples_are_ignored(anomalies):
    assert pick(anomalies[1], 3) == []


def test_unfinished_period_is_not_judged(anomalies):
    assert pick(anomalies[1], 4) == []


def test_short_history_is_not_judged(anomalies):
    assert pick(anomalies[1], 5) == []


def test_weekly_rollups_and_score_rise(anomalies):
    found = pick(anomalies[1], 6)
    assert [(r["kind"], r["grain"], str(r["period_start"])) for r in found] == [
        ("review_score_rise", "week", "2026-08-24")
    ]
    assert str(found[0]["period_end"]) == "2026-08-31"


def test_latest_snapshot_wins_for_a_day(anomalies):
    found = pick(anomalies[1], 7)
    assert [(r["kind"], r["grain"], str(r["period_start"])) for r in found] == [
        ("review_score_drop", "day", "2026-11-03")
    ]
    assert found[0]["value"] == pytest.approx(0.5)


def test_ids_are_unique_and_stable(anomalies):
    data_dir, rows = anomalies
    ids = [r["anomaly_id"] for r in rows]
    assert len(set(ids)) == len(ids)
    model.run(data_dir)
    assert [r["anomaly_id"] for r in model.load_anomalies(data_dir)] == ids


def test_no_review_data_gives_empty_result(tmp_path):
    assert model.run(tmp_path) == 0
    assert model.load_anomalies(tmp_path) == []
    assert model.load_episodes(tmp_path) == []


def episodes_of(data_dir, appid):
    return [e for e in model.load_episodes(data_dir) if e["appid"] == appid]


def test_neighbouring_periods_form_one_episode(anomalies):
    data_dir, rows = anomalies
    first, second = episodes_of(data_dir, 9)
    assert (str(first["period_start"]), str(first["period_end"]), first["periods"]) == ("2026-01-01", "2026-04-01", 3)
    assert first["direction"] == "negative"
    assert (first["reviews"], first["positive"], first["negative"]) == (3000, 1800, 1200)
    assert first["share_positive"] == pytest.approx(0.6)
    assert first["baseline_share"] == pytest.approx(0.905, abs=0.01)
    assert first["volume_spike"] is False
    assert first["is_open"] is False
    assert (str(second["period_start"]), second["periods"]) == ("2026-06-01", 1)
    assert second["volume_spike"] is True
    assert second["peak_volume_ratio"] == pytest.approx(5.0)
    # Every anomaly row points at its episode.
    mine = pick(rows, 9)
    assert {r["episode_id"] for r in mine} == {first["episode_id"], second["episode_id"]}
    assert sum(1 for r in mine if r["episode_id"] == first["episode_id"]) == 3


def test_episode_directions_and_open_flag(anomalies):
    data_dir, _ = anomalies
    assert [e["direction"] for e in episodes_of(data_dir, 2)] == ["volume"]
    assert [e["direction"] for e in episodes_of(data_dir, 6)] == ["positive"]
    # The last finished day in the data: the episode may still be running.
    assert [e["is_open"] for e in episodes_of(data_dir, 7)] == [True]
    assert [e["is_open"] for e in episodes_of(data_dir, 1)] == [False]


def test_episode_ids_are_unique(anomalies):
    ids = [e["episode_id"] for e in model.load_episodes(anomalies[0])]
    assert len(set(ids)) == len(ids)
