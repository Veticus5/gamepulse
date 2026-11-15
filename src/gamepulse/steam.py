"""Thin client for the public Steam endpoints (no API key needed).

Checked on 2026-11-14. The review histogram lives on the store host and is
not part of the official Web API, so it may change without notice.
"""

from typing import Any

import httpx

API_BASE = "https://api.steampowered.com"
STORE_BASE = "https://store.steampowered.com"
USER_AGENT = "gamepulse-collector/0.1"
TIMEOUT_SECONDS = 20.0


class FetchError(Exception):
    """The remote service did not return the data we asked for."""


SteamError = FetchError


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        transport=transport,
        timeout=TIMEOUT_SECONDS,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=False,
    )


def get_json(client: httpx.Client, url: str, params: dict[str, Any] | None = None) -> Any:
    """GET a URL and decode JSON; every failure becomes a FetchError."""
    try:
        response = client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise FetchError(f"{type(exc).__name__}: {exc}") from exc
    if response.status_code != 200:
        raise FetchError(f"HTTP {response.status_code} from {response.url.path}")
    try:
        return response.json()
    except ValueError as exc:
        raise FetchError(f"non-JSON response from {response.url.path}") from exc


def _get_json(client: httpx.Client, url: str, params: dict[str, Any] | None = None) -> dict:
    body = get_json(client, url, params)
    if not isinstance(body, dict):
        raise SteamError(f"unexpected JSON from {url}")
    return body


def fetch_ccu(client: httpx.Client, appid: int) -> int:
    """Current number of players in the game."""
    body = _get_json(
        client,
        f"{API_BASE}/ISteamUserStats/GetNumberOfCurrentPlayers/v1/",
        {"appid": appid},
    )
    data = body.get("response")
    if not isinstance(data, dict) or data.get("result") != 1:
        raise SteamError(f"no player count for appid {appid}")
    count = data.get("player_count")
    if not isinstance(count, int) or isinstance(count, bool):
        raise SteamError(f"no player count for appid {appid}")
    return count


def fetch_news_page(
    client: httpx.Client,
    appid: int,
    *,
    count: int = 100,
    enddate: int | None = None,
) -> list[dict]:
    """One page of news, newest first; ``enddate`` (unix time) pages backwards."""
    params: dict[str, Any] = {"appid": appid, "count": count, "maxlength": 0}
    if enddate is not None:
        params["enddate"] = enddate
    body = _get_json(client, f"{API_BASE}/ISteamNews/GetNewsForApp/v2/", params)
    appnews = body.get("appnews")
    items = appnews.get("newsitems") if isinstance(appnews, dict) else None
    if not isinstance(items, list):
        raise SteamError(f"no news list for appid {appid}")
    return [item for item in items if isinstance(item, dict)]


def fetch_review_histogram(client: httpx.Client, appid: int) -> dict:
    """Positive and negative review counts over time (monthly and last 30 days)."""
    body = _get_json(client, f"{STORE_BASE}/appreviewhistogram/{appid}", {"l": "english"})
    results = body.get("results")
    if body.get("success") != 1 or not isinstance(results, dict):
        raise SteamError(f"no review histogram for appid {appid}")
    return results


def fetch_app_details(client: httpx.Client, appid: int) -> dict:
    """Store page data for a game (name, studio, release date, genres, images).

    A store endpoint, not part of the official Web API.
    """
    body = _get_json(
        client,
        f"{STORE_BASE}/api/appdetails",
        {"appids": appid, "cc": "US", "l": "english"},
    )
    entry = body.get(str(appid))
    data = entry.get("data") if isinstance(entry, dict) else None
    if not isinstance(entry, dict) or entry.get("success") is not True or not isinstance(data, dict):
        raise SteamError(f"no store details for appid {appid}")
    return data


def fetch_reviews_page(client: httpx.Client, appid: int, cursor: str = "*") -> tuple[list[dict], str | None]:
    """One page of up to 100 user reviews in every language, newest first,
    and the cursor of the next page (None at the end of the history).

    A store endpoint, not part of the official Web API. The official
    IUserReviewsService/GetAppReviews ignores the "recent" order (checked
    2026-11-15), so it cannot be walked backwards in time.
    """
    body = _get_json(
        client,
        f"{STORE_BASE}/ajaxappreviews/{appid}",
        {
            "json": 1, "filter": "recent", "language": "all", "purchase_type": "all", "review_type": "all",
            "num_per_page": 100, "filter_offtopic_activity": 0, "cursor": cursor,
        },
    )
    reviews = body.get("reviews")
    if body.get("success") != 1 or not isinstance(reviews, list):
        raise SteamError(f"no reviews for appid {appid}")
    reviews = [r for r in reviews if isinstance(r, dict)]
    following = body.get("cursor")
    if not reviews or not isinstance(following, str) or following == cursor:
        following = None
    return reviews, following
