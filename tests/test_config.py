from pathlib import Path

import pytest

from gamepulse.config import Game, load_games

REPO = Path(__file__).resolve().parent.parent


def write(tmp_path, text):
    path = tmp_path / "games.toml"
    path.write_text(text)
    return path


def test_load_games_reads_appid_and_name(tmp_path):
    path = write(
        tmp_path,
        '[[games]]\nappid = 730\nname = "Counter-Strike 2"\n'
        '[[games]]\nappid = 570\nname = "Dota 2"\n',
    )
    assert load_games(path) == [Game(730, "Counter-Strike 2"), Game(570, "Dota 2")]


def test_load_games_rejects_duplicate_appid(tmp_path):
    path = write(
        tmp_path,
        '[[games]]\nappid = 730\nname = "A"\n[[games]]\nappid = 730\nname = "B"\n',
    )
    with pytest.raises(ValueError):
        load_games(path)


def test_load_games_rejects_empty_file(tmp_path):
    with pytest.raises(ValueError):
        load_games(write(tmp_path, ""))


def test_repo_games_toml_loads():
    games = load_games(REPO / "games.toml")
    assert games
    assert all(g.appid > 0 and g.name for g in games)
