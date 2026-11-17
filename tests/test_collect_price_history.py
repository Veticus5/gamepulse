import httpx

from gamepulse import collect_price_history
from gamepulse.storage import read_jsonl

NOW = "2026-11-17T10:00:00Z"


def change(ts, final, regular, cut, shop=61):
    return {
        "timestamp": ts,
        "shop": {"id": shop, "name": "Steam"},
        "deal": {
            "price": {"amount": final / 100, "amountInt": final, "currency": "USD"},
            "regular": {"amount": regular / 100, "amountInt": regular, "currency": "USD"},
            "cut": cut,
        },
    }


def handler_for(seen):
    def handler(request):
        seen.append((request.url.path, dict(request.url.params), request.headers.get("ITAD-API-Key")))
        if request.url.path == "/games/lookup/v1":
            if request.url.params["appid"] == "730":
                return httpx.Response(200, json={"found": False})
            return httpx.Response(200, json={"found": True, "game": {"id": "uuid-570"}})
        return httpx.Response(200, json=[
            change("2025-12-04T19:20:48+01:00", 2999, 2999, 0),
            change("2025-11-20T19:23:05+01:00", 1499, 2999, 50),
            change("2025-11-01T01:00:00+01:00", 2999, 2999, 0, shop=6),  # another shop slipped in
        ])
    return handler


def test_run_stores_the_steam_price_changes(tmp_path, games, client_for):
    seen = []
    done = collect_price_history.run(client_for(handler_for(seen)), games, tmp_path, key="secret", days=400, pause=0, now=NOW)
    assert done == 1  # 730 is unknown to the service
    assert [path for path, _, _ in seen] == ["/games/lookup/v1", "/games/lookup/v1", "/games/history/v2"]
    assert all(key == "secret" for _, _, key in seen)
    assert seen[2][1] == {"id": "uuid-570", "country": "US", "shops": "61", "since": "2025-10-13T10:00:00Z"}
    rows = read_jsonl(tmp_path / "raw" / "price_history" / "570.jsonl")
    assert [(r["ts"], r["final"], r["initial"], r["discount_percent"]) for r in rows] == [
        ("2025-11-20T18:23:05Z", 1499, 2999, 50),
        ("2025-12-04T18:20:48Z", 2999, 2999, 0),
    ]
    assert {(r["appid"], r["currency"], r["fetched_at"], r["since"]) for r in rows} == {
        (570, "USD", NOW, "2025-10-13T10:00:00Z")
    }
    assert not (tmp_path / "raw" / "price_history" / "730.jsonl").exists()


def test_second_run_replaces_the_file_and_reuses_the_game_id(tmp_path, games, client_for):
    seen = []
    client = client_for(handler_for(seen))
    collect_price_history.run(client, games, tmp_path, key="k", pause=0, now=NOW)
    seen.clear()
    collect_price_history.run(client, games, tmp_path, key="k", pause=0, now=NOW)
    # Only the game that was not found is looked up again.
    assert [(path, params.get("appid")) for path, params, _ in seen if path.endswith("lookup/v1")] == [("/games/lookup/v1", "730")]
    assert len(read_jsonl(tmp_path / "raw" / "price_history" / "570.jsonl")) == 2


def test_refused_key_or_rate_limit_stops_and_keeps_old_data(tmp_path, games, client_for):
    collect_price_history.run(client_for(handler_for([])), games, tmp_path, key="k", pause=0, now=NOW)
    calls = []

    def refused(request):
        calls.append(request.url.path)
        return httpx.Response(403, json={"reason_phrase": "Invalid or expired api key"})

    assert collect_price_history.run(client_for(refused), games, tmp_path, key="bad", pause=0, now=NOW) == 0
    assert len(calls) == 1  # no point in asking again with the same key
    assert len(read_jsonl(tmp_path / "raw" / "price_history" / "570.jsonl")) == 2


def test_api_key_comes_from_environment_or_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("ITAD_API_KEY", raising=False)
    assert collect_price_history.api_key(tmp_path / ".env") is None
    (tmp_path / ".env").write_text("OTHER=1\nITAD_API_KEY=from-file\n")
    assert collect_price_history.api_key(tmp_path / ".env") == "from-file"
    monkeypatch.setenv("ITAD_API_KEY", "from-env")
    assert collect_price_history.api_key(tmp_path / ".env") == "from-env"
