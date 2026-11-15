import httpx

from gamepulse import collect_prices
from gamepulse.storage import read_jsonl

BODY = {
    "730": {"success": True, "data": []},  # free to play: no price
    "570": {"success": True, "data": {"price_overview": {
        "currency": "USD", "initial": 3999, "final": 2799, "discount_percent": 30, "final_formatted": "$27.99"}}},
}


def test_run_stores_price_and_discount_for_every_game(tmp_path, games, client_for):
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=BODY)

    assert collect_prices.run(client_for(handler), games, tmp_path) == 2
    assert seen == [{"appids": "730,570", "cc": "US", "filters": "price_overview"}]  # one request for all games
    (path,) = (tmp_path / "raw" / "prices").glob("*.jsonl")
    rows = {row["appid"]: row for row in read_jsonl(path)}
    assert rows[570]["priced"] is True
    assert (rows[570]["initial"], rows[570]["final"], rows[570]["discount_percent"], rows[570]["currency"]) == (3999, 2799, 30, "USD")
    assert rows[730]["priced"] is False and rows[730]["discount_percent"] is None
    assert rows[730]["ts"].endswith("Z") and path.stem == rows[730]["ts"][:10]


def test_game_without_an_answer_gets_no_row(tmp_path, games, client_for):
    body = {"730": {"success": False}, "570": BODY["570"]}
    assert collect_prices.run(client_for(lambda request: httpx.Response(200, json=body)), games, tmp_path) == 1
    (path,) = (tmp_path / "raw" / "prices").glob("*.jsonl")
    assert [row["appid"] for row in read_jsonl(path)] == [570]


def test_failures_store_nothing(tmp_path, games, client_for):
    assert collect_prices.run(client_for(lambda request: httpx.Response(429)), games, tmp_path) == 0
    assert collect_prices.run(client_for(lambda request: httpx.Response(200, json={})), games, tmp_path) == 0
    assert not (tmp_path / "raw" / "prices").exists()
