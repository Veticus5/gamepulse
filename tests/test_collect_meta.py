import httpx

from gamepulse import collect_meta
from gamepulse.storage import read_jsonl

DETAILS = {
    "name": "WARDOGS",
    "type": "game",
    "developers": ["BULKHEAD"],
    "release_date": {"coming_soon": False, "date": "Sep 10, 2026"},
    "genres": [{"id": "1", "description": "Action"}],
    "header_image": "https://example.invalid/header.jpg",
    "detailed_description": "x" * 5000,
}


def ok_handler(request):
    appid = request.url.params["appids"]
    return httpx.Response(200, json={appid: {"success": True, "data": DETAILS}})


def stored(data_dir, appid):
    return read_jsonl(data_dir / "raw" / "appdetails" / f"{appid}.jsonl")


def test_run_stores_selected_fields_per_game(tmp_path, games, client_for):
    assert collect_meta.run(client_for(ok_handler), games, tmp_path, pause=0) == 2
    row = stored(tmp_path, 730)[0]
    assert row["appid"] == 730
    assert row["details"]["developers"] == ["BULKHEAD"]
    assert row["details"]["release_date"]["date"] == "Sep 10, 2026"
    assert row["details"]["website"] is None
    assert "detailed_description" not in row["details"]


def test_unknown_game_is_skipped_and_rest_continues(tmp_path, games, client_for):
    def handler(request):
        if request.url.params["appids"] == "730":
            return httpx.Response(200, json={"730": {"success": False}})
        return ok_handler(request)

    assert collect_meta.run(client_for(handler), games, tmp_path, pause=0) == 1
    assert stored(tmp_path, 730) == []
    assert len(stored(tmp_path, 570)) == 1
