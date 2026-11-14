"""Game list configuration."""

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Game:
    appid: int
    name: str


def load_games(path: Path) -> list[Game]:
    """Read the tracked games from a TOML file with ``[[games]]`` tables."""
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    games = [Game(int(g["appid"]), str(g["name"])) for g in raw.get("games", [])]
    if not games:
        raise ValueError(f"{path}: no games defined")
    appids = [g.appid for g in games]
    duplicates = sorted({a for a in appids if appids.count(a) > 1})
    if duplicates:
        raise ValueError(f"{path}: duplicate appid {duplicates}")
    return games
