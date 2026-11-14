import httpx

from gamepulse import collect_news
from gamepulse.config import Game
from gamepulse.storage import append_jsonl, read_jsonl

GAME = [Game(730, "Counter-Strike 2")]


def make_items(n, *, start_date=1_000_000, step=60, prefix="g"):
    """n items, newest first, one per minute."""
    return [
        {"gid": f"{prefix}{i}", "title": f"t{i}", "date": start_date + (n - i) * step, "appid": 730}
        for i in range(n)
    ]


class FakeSteam:
    """Serves news like Steam: newest first, `count` per page, `enddate` inclusive."""

    def __init__(self, items_by_appid):
        self.items = items_by_appid
        self.calls = []
        self.fail_when = lambda params: False

    def __call__(self, request):
        params = request.url.params
        self.calls.append(dict(params))
        if self.fail_when(params):
            return httpx.Response(503)
        appid = int(params["appid"])
        if appid not in self.items:
            return httpx.Response(500)
        items = sorted(self.items[appid], key=lambda i: i["date"], reverse=True)
        if "enddate" in params:
            items = [i for i in items if i["date"] <= int(params["enddate"])]
        page = items[: int(params["count"])]
        return httpx.Response(
            200, json={"appnews": {"appid": appid, "newsitems": page, "count": len(self.items[appid])}}
        )


def stored(data_dir, appid=730):
    return read_jsonl(data_dir / "raw" / "news" / f"{appid}.jsonl")


def gids(data_dir, appid=730):
    return [r["gid"] for r in stored(data_dir, appid)]


def test_backfill_walks_all_pages(tmp_path, client_for):
    fake = FakeSteam({730: make_items(250)})
    assert collect_news.run(client_for(fake), GAME, tmp_path, pause=0) == 1
    assert len(gids(tmp_path)) == 250
    assert len(set(gids(tmp_path))) == 250


def test_second_run_adds_nothing(tmp_path, client_for):
    fake = FakeSteam({730: make_items(250)})
    collect_news.run(client_for(fake), GAME, tmp_path, pause=0)
    fake.calls.clear()
    collect_news.run(client_for(fake), GAME, tmp_path, pause=0)
    assert len(gids(tmp_path)) == 250
    assert len(fake.calls) == 1


def test_incremental_fetches_only_new(tmp_path, client_for):
    items = make_items(250)
    fake = FakeSteam({730: items})
    collect_news.run(client_for(fake), GAME, tmp_path, pause=0)
    newest = max(i["date"] for i in items)
    items.extend({"gid": f"new{i}", "date": newest + 60 * (i + 1), "appid": 730} for i in range(3))
    collect_news.run(client_for(fake), GAME, tmp_path, pause=0)
    assert len(gids(tmp_path)) == 253
    assert set(gids(tmp_path)[-3:]) == {"new0", "new1", "new2"}


def test_boundary_gid_not_duplicated(tmp_path, client_for):
    # enddate is inclusive, so the oldest item of a page comes back on the next one.
    fake = FakeSteam({730: make_items(25)})
    collect_news.run(client_for(fake), GAME, tmp_path, pause=0, page_size=10)
    assert len(fake.calls) > 1
    assert sorted(gids(tmp_path)) == sorted(f"g{i}" for i in range(25))


def test_full_resumes_interrupted_backfill(tmp_path, client_for):
    items = make_items(250)
    fake = FakeSteam({730: items})
    append_jsonl(tmp_path / "raw" / "news" / "730.jsonl", items[:100])
    collect_news.run(client_for(fake), GAME, tmp_path, pause=0)
    assert len(gids(tmp_path)) == 100
    collect_news.run(client_for(fake), GAME, tmp_path, pause=0, full=True)
    assert len(gids(tmp_path)) == 250
    assert len(set(gids(tmp_path))) == 250


def test_same_timestamp_page_terminates(tmp_path, client_for):
    items = [{"gid": f"s{i}", "date": 5000, "appid": 730} for i in range(150)]
    fake = FakeSteam({730: items})
    assert collect_news.run(client_for(fake), GAME, tmp_path, pause=0, full=True) == 1
    assert len(gids(tmp_path)) == 100
    assert len(fake.calls) < 10


def test_error_on_one_game_continues(tmp_path, client_for):
    games = [Game(1, "Broken"), Game(730, "Counter-Strike 2")]
    fake = FakeSteam({730: make_items(5)})
    assert collect_news.run(client_for(fake), games, tmp_path, pause=0) == 1
    assert len(gids(tmp_path)) == 5
    assert not (tmp_path / "raw" / "news" / "1.jsonl").exists()


def test_game_without_news_counts_as_success(tmp_path, client_for):
    fake = FakeSteam({730: []})
    assert collect_news.run(client_for(fake), GAME, tmp_path, pause=0) == 1


def test_item_without_gid_is_skipped(tmp_path, client_for):
    fake = FakeSteam({730: [{"title": "no gid", "date": 10}, {"gid": "ok", "date": 5}]})
    assert collect_news.run(client_for(fake), GAME, tmp_path, pause=0) == 1
    assert gids(tmp_path) == ["ok"]


def test_records_have_fetched_at(tmp_path, client_for):
    fake = FakeSteam({730: make_items(2)})
    collect_news.run(client_for(fake), GAME, tmp_path, pause=0)
    rows = stored(tmp_path)
    assert all(r["fetched_at"].endswith("Z") for r in rows)
    assert rows[0]["title"] == "t0"


def test_item_with_line_separator_not_duplicated_on_rerun(tmp_path, client_for):
    items = [{"gid": "a", "date": 20, "contents": "one\u2028two"}, {"gid": "b", "date": 10}]
    fake = FakeSteam({730: items})
    for _ in range(3):
        collect_news.run(client_for(fake), GAME, tmp_path, pause=0)
    assert sorted(gids(tmp_path)) == ["a", "b"]


def test_interrupted_incremental_walk_resumes_on_next_run(tmp_path, client_for):
    items = make_items(200)
    fake = FakeSteam({730: items})
    append_jsonl(tmp_path / "raw" / "news" / "730.jsonl", items[150:])  # 50 oldest stored
    fake.fail_when = lambda params: "enddate" in params  # every page after the first fails
    assert collect_news.run(client_for(fake), GAME, tmp_path, pause=0) == 0
    assert len(gids(tmp_path)) == 150  # 50 old + newest page, hole in between
    fake.fail_when = lambda params: False
    assert collect_news.run(client_for(fake), GAME, tmp_path, pause=0) == 1
    assert sorted(gids(tmp_path)) == sorted(i["gid"] for i in items)


def test_interrupted_first_backfill_resumes_without_full(tmp_path, client_for):
    fake = FakeSteam({730: make_items(250)})
    budget = {"left": 2}

    def fail_after_two(params):
        budget["left"] -= 1
        return budget["left"] < 0

    fake.fail_when = fail_after_two
    assert collect_news.run(client_for(fake), GAME, tmp_path, pause=0) == 0
    assert 0 < len(gids(tmp_path)) < 250
    fake.fail_when = lambda params: False
    assert collect_news.run(client_for(fake), GAME, tmp_path, pause=0) == 1
    assert len(set(gids(tmp_path))) == len(gids(tmp_path)) == 250


def test_no_resume_state_left_after_complete_walk(tmp_path, client_for):
    fake = FakeSteam({730: make_items(250)})
    collect_news.run(client_for(fake), GAME, tmp_path, pause=0)
    assert not list((tmp_path / "state").rglob("*.json"))


def test_unexpected_error_in_one_game_does_not_stop_the_rest(tmp_path, client_for, monkeypatch):
    games = [Game(1, "Explodes"), Game(730, "Counter-Strike 2")]
    fake = FakeSteam({730: make_items(5)})
    real = collect_news.fetch_news_page

    def flaky(client, appid, **kwargs):
        if appid == 1:
            raise RuntimeError("boom")
        return real(client, appid, **kwargs)

    monkeypatch.setattr(collect_news, "fetch_news_page", flaky)
    assert collect_news.run(client_for(fake), games, tmp_path, pause=0) == 1
    assert len(gids(tmp_path)) == 5


def test_page_without_dates_fails_the_game_instead_of_passing(tmp_path, client_for):
    items = [{"gid": f"x{i}", "date": "yesterday"} for i in range(10)]
    fake = FakeSteam({730: []})
    fake.items[730] = items
    fake.__class__ = type("NoSort", (FakeSteam,), {"__call__": lambda self, request: httpx.Response(
        200, json={"appnews": {"appid": 730, "newsitems": items, "count": 10}})})
    assert collect_news.run(client_for(fake), GAME, tmp_path, pause=0, full=True) == 0
