import httpx

from gamepulse import collect_ccu
from gamepulse.storage import read_jsonl

COUNTS = {"730": 1285590, "570": 851507}


def ok_handler(request):
    appid = request.url.params["appid"]
    return httpx.Response(200, json={"response": {"player_count": COUNTS[appid], "result": 1}})


def records(data_dir):
    files = sorted((data_dir / "raw" / "ccu").glob("*.jsonl"))
    return files, [r for f in files for r in read_jsonl(f)]


def test_run_writes_one_record_per_game(tmp_path, games, client_for):
    assert collect_ccu.run(client_for(ok_handler), games, tmp_path, pause=0) == 2
    _, rows = records(tmp_path)
    assert [(r["appid"], r["player_count"], r["ok"], r["error"]) for r in rows] == [
        (730, 1285590, True, None),
        (570, 851507, True, None),
    ]


def test_run_records_failure_and_continues(tmp_path, games, client_for):
    def handler(request):
        if request.url.params["appid"] == "730":
            return httpx.Response(404, json={"response": {"result": 42}})
        return ok_handler(request)

    assert collect_ccu.run(client_for(handler), games, tmp_path, pause=0) == 1
    _, rows = records(tmp_path)
    assert rows[0]["appid"] == 730
    assert rows[0]["ok"] is False
    assert rows[0]["player_count"] is None
    assert rows[0]["error"]
    assert (rows[1]["appid"], rows[1]["player_count"], rows[1]["ok"]) == (570, 851507, True)


def test_run_all_fail_returns_zero(tmp_path, games, client_for):
    def handler(request):
        raise httpx.ConnectError("no network", request=request)

    assert collect_ccu.run(client_for(handler), games, tmp_path, pause=0) == 0
    _, rows = records(tmp_path)
    assert [r["ok"] for r in rows] == [False, False]


def test_file_named_by_utc_date(tmp_path, games, client_for):
    collect_ccu.run(client_for(ok_handler), games, tmp_path, pause=0)
    files, rows = records(tmp_path)
    assert len(files) == 1
    assert files[0].stem == rows[0]["ts"][:10]


def test_unexpected_error_is_recorded_and_does_not_stop_the_rest(tmp_path, games, client_for, monkeypatch):
    real = collect_ccu.fetch_ccu

    def flaky(client, appid):
        if appid == 730:
            raise RuntimeError("boom")
        return real(client, appid)

    monkeypatch.setattr(collect_ccu, "fetch_ccu", flaky)
    assert collect_ccu.run(client_for(ok_handler), games, tmp_path, pause=0) == 1
    _, rows = records(tmp_path)
    assert [(r["appid"], r["ok"]) for r in rows] == [(730, False), (570, True)]
    assert "boom" in rows[0]["error"]
