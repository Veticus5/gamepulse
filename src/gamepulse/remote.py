"""Player counts only, for running where the rest of the project is not installed.

Player counts are the one thing Steam keeps no history of, so they are
collected around the clock by a scheduled GitHub Actions workflow instead
of a computer that is switched off at night. This entry point imports
nothing but the two collectors (httpx is the only dependency), so a run
needs no project install and finishes in seconds:

    PYTHONPATH=src python -m gamepulse.remote --games games.toml --data-dir out
"""

import argparse
import logging
import sys
from pathlib import Path

from gamepulse import collect_ccu, collect_fivem
from gamepulse.config import load_games
from gamepulse.steam import make_client


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gamepulse.remote", description="Player counts from Steam and FiveM.")
    parser.add_argument("--games", type=Path, default=Path("games.toml"))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    games = load_games(args.games)
    with make_client() as client:
        steam = collect_ccu.run(client, games, args.data_dir)
        fivem = collect_fivem.run(client, args.data_dir)
    return 0 if steam or fivem else 1


if __name__ == "__main__":
    sys.exit(main())
