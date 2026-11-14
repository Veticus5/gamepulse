"""Command line entry point: ``gamepulse ccu|news|reviews|fivem``."""

import argparse
import fcntl
import logging
import sys
from pathlib import Path
from typing import IO

from gamepulse import collect_ccu, collect_fivem, collect_news, collect_reviews
from gamepulse.config import load_games
from gamepulse.steam import make_client


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gamepulse", description="Game data collectors.")
    data = argparse.ArgumentParser(add_help=False)
    data.add_argument("--data-dir", type=Path, default=Path("data"), help="where raw data goes")
    steam = argparse.ArgumentParser(add_help=False, parents=[data])
    steam.add_argument("--games", type=Path, default=Path("games.toml"), help="game list (TOML)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ccu", parents=[steam], help="current player counts from Steam")
    news = sub.add_parser("news", parents=[steam], help="Steam news items not stored yet")
    news.add_argument(
        "--full",
        action="store_true",
        help="walk the whole history (first run, new games, or after an interrupted run)",
    )
    sub.add_parser("reviews", parents=[steam], help="Steam review histogram snapshot")
    sub.add_parser("fivem", parents=[data], help="FiveM total player counts (not from Steam)")
    return parser


def _acquire_lock(data_dir: Path, command: str) -> IO | None:
    """Take the per-collector lock; None means another run already holds it."""
    path = data_dir / "locks" / f"{command}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request otherwise
    games = []
    if args.command != "fivem":
        try:
            games = load_games(args.games)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"gamepulse: cannot load games from {args.games}: {exc}", file=sys.stderr)
            return 1
    # Two runs of the same collector would store the same news twice.
    lock = _acquire_lock(args.data_dir, args.command)
    if lock is None:
        logging.warning("%s: another run is in progress, skipping this one", args.command)
        return 0
    with lock, make_client() as client:
        if args.command == "ccu":
            succeeded = collect_ccu.run(client, games, args.data_dir)
        elif args.command == "news":
            succeeded = collect_news.run(client, games, args.data_dir, full=args.full)
        elif args.command == "reviews":
            succeeded = collect_reviews.run(client, games, args.data_dir)
        else:
            succeeded = collect_fivem.run(client, args.data_dir)
    return 0 if succeeded else 1

if __name__ == "__main__":
    sys.exit(main())
