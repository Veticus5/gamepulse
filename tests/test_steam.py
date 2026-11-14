import httpx
import pytest

from gamepulse.steam import (
    SteamError,
    fetch_ccu,
    fetch_news_page,
    fetch_review_histogram,
    make_client,
)


def client_for(handler):
    return make_client(httpx.MockTransport(handler))


def test_fetch_ccu_returns_player_count():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"response": {"player_count": 1285590, "result": 1}})

    assert fetch_ccu(client_for(handler), 730) == 1285590
    assert seen[0].url.host == "api.steampowered.com"
    assert seen[0].url.params["appid"] == "730"
    assert seen[0].headers["user-agent"] == "gamepulse-collector/0.1"


def test_fetch_ccu_unknown_app_raises():
    handler = lambda request: httpx.Response(404, json={"response": {"result": 42}})
    with pytest.raises(SteamError):
        fetch_ccu(client_for(handler), 999999999)


def test_fetch_ccu_result_not_one_raises():
    handler = lambda request: httpx.Response(200, json={"response": {"result": 42}})
    with pytest.raises(SteamError):
        fetch_ccu(client_for(handler), 730)


def test_fetch_ccu_html_body_raises():
    handler = lambda request: httpx.Response(200, text="<!DOCTYPE html><html></html>")
    with pytest.raises(SteamError):
        fetch_ccu(client_for(handler), 730)


def test_fetch_ccu_redirect_raises():
    handler = lambda request: httpx.Response(
        302, headers={"Location": "https://store.steampowered.com/"}
    )
    with pytest.raises(SteamError):
        fetch_ccu(client_for(handler), 730)


def test_fetch_ccu_network_error_raises():
    def handler(request):
        raise httpx.ConnectError("no network", request=request)

    with pytest.raises(SteamError):
        fetch_ccu(client_for(handler), 730)


def test_fetch_news_page_sends_params():
    seen = []
    items = [{"gid": "1", "date": 10}, {"gid": "2", "date": 5}]

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"appnews": {"appid": 730, "newsitems": items, "count": 2}})

    client = client_for(handler)
    assert fetch_news_page(client, 730) == items
    params = seen[0].url.params
    assert params["appid"] == "730"
    assert params["count"] == "100"
    assert params["maxlength"] == "0"
    assert "enddate" not in params

    fetch_news_page(client, 730, count=50, enddate=1700000000)
    params = seen[1].url.params
    assert params["count"] == "50"
    assert params["enddate"] == "1700000000"


def test_fetch_news_page_missing_appnews_raises():
    handler = lambda request: httpx.Response(200, json={})
    with pytest.raises(SteamError):
        fetch_news_page(client_for(handler), 730)


def test_fetch_review_histogram_returns_results():
    seen = []
    results = {"rollup_type": "month", "rollups": [{"date": 1, "recommendations_up": 2, "recommendations_down": 0}], "recent": []}

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"success": 1, "results": results})

    assert fetch_review_histogram(client_for(handler), 413150) == results
    assert seen[0].url.host == "store.steampowered.com"
    assert seen[0].url.path == "/appreviewhistogram/413150"


def test_fetch_review_histogram_success_zero_raises():
    handler = lambda request: httpx.Response(200, json={"success": 0})
    with pytest.raises(SteamError):
        fetch_review_histogram(client_for(handler), 413150)
