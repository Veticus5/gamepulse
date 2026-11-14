import httpx

from gamepulse import collect_reviews
from gamepulse.storage import read_jsonl

RESULTS = {
    "start_date": 1456444800,
    "end_date": 1794614400,
    "rollup_type": "month",
    "rollups": [{"date": 1454284800, "recommendations_up": 1701, "recommendations_down": 15}],
    "recent": [{"date": 1792108800, "recommendations_up": 203, "recommendations_down": 6}],
    "weeks": [],
}


def ok_handler(request):
    return httpx.Response(200, json={"success": 1, "results": RESULTS})


def stored(data_dir, appid):
    return read_jsonl(data_dir / "raw" / "review_histogram" / f"{appid}.jsonl")


def test_run_appends_snapshot_per_game(tmp_path, games, client_for):
    assert collect_reviews.run(client_for(ok_handler), games, tmp_path, pause=0) == 2
    for appid in (730, 570):
        rows = stored(tmp_path, appid)
        assert len(rows) == 1
        assert rows[0]["appid"] == appid
        assert rows[0]["results"] == RESULTS
        assert rows[0]["fetched_at"].endswith("Z")


def test_second_run_appends_second_snapshot(tmp_path, games, client_for):
    client = client_for(ok_handler)
    collect_reviews.run(client, games, tmp_path, pause=0)
    collect_reviews.run(client, games, tmp_path, pause=0)
    assert len(stored(tmp_path, 730)) == 2


def test_error_on_one_game_continues(tmp_path, games, client_for):
    def handler(request):
        if request.url.path.endswith("/730"):
            return httpx.Response(302, headers={"Location": "https://store.steampowered.com/"})
        return ok_handler(request)

    assert collect_reviews.run(client_for(handler), games, tmp_path, pause=0) == 1
    assert not (tmp_path / "raw" / "review_histogram" / "730.jsonl").exists()
    assert len(stored(tmp_path, 570)) == 1


def test_unexpected_error_does_not_stop_the_rest(tmp_path, games, client_for, monkeypatch):
    real = collect_reviews.fetch_review_histogram

    def flaky(client, appid):
        if appid == 730:
            raise RuntimeError("boom")
        return real(client, appid)

    monkeypatch.setattr(collect_reviews, "fetch_review_histogram", flaky)
    assert collect_reviews.run(client_for(ok_handler), games, tmp_path, pause=0) == 1
    assert len(stored(tmp_path, 570)) == 1
