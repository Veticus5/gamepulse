import httpx
import pytest

from gamepulse import cli
from gamepulse.steam import make_client

GAMES_TOML = '[[games]]\nappid = 730\nname = "Counter-Strike 2"\n'


@pytest.fixture
def args(tmp_path):
    games = tmp_path / "games.toml"
    games.write_text(GAMES_TOML)
    return ["--games", str(games), "--data-dir", str(tmp_path / "data")]


def use_handler(monkeypatch, handler):
    monkeypatch.setattr(cli, "make_client", lambda: make_client(httpx.MockTransport(handler)))


def test_cli_ccu_exit_zero_on_success(monkeypatch, args, tmp_path):
    use_handler(
        monkeypatch,
        lambda request: httpx.Response(200, json={"response": {"player_count": 5, "result": 1}}),
    )
    assert cli.main(["ccu", *args]) == 0
    assert list((tmp_path / "data" / "raw" / "ccu").glob("*.jsonl"))


def test_cli_ccu_exit_one_when_everything_fails(monkeypatch, args):
    use_handler(monkeypatch, lambda request: httpx.Response(500))
    assert cli.main(["ccu", *args]) == 1


def test_cli_missing_games_file_exits_one(monkeypatch, tmp_path, capsys):
    use_handler(monkeypatch, lambda request: httpx.Response(500))
    assert cli.main(["ccu", "--games", str(tmp_path / "nope.toml")]) == 1
    assert "nope.toml" in capsys.readouterr().err


def test_cli_news_full_flag_reaches_collector(monkeypatch, args):
    seen = {}

    def fake_run(client, games, data_dir, *, full=False):
        seen["full"] = full
        return 1

    monkeypatch.setattr(cli.collect_news, "run", fake_run)
    assert cli.main(["news", "--full", *args]) == 0
    assert seen["full"] is True


def test_cli_reviews_runs_collector(monkeypatch, args, tmp_path):
    use_handler(
        monkeypatch,
        lambda request: httpx.Response(200, json={"success": 1, "results": {"rollups": []}}),
    )
    assert cli.main(["reviews", *args]) == 0
    assert (tmp_path / "data" / "raw" / "review_histogram" / "730.jsonl").exists()


def test_cli_fivem_needs_no_games_file(monkeypatch, tmp_path):
    use_handler(monkeypatch, lambda request: httpx.Response(200, json=[1, 2, 3]))
    data_dir = tmp_path / "data"
    assert cli.main(["fivem", "--data-dir", str(data_dir)]) == 0
    assert list((data_dir / "raw" / "fivem").glob("*.jsonl"))
