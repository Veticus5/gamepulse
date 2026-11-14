"""Command line entry point: ``gamepulse ccu|news|reviews``."""

import argparse
import logging
import sys
from pathlib import Path

from gamepulse import collect_ccu, collect_news, collect_reviews
from gamepulse.config import load_games
from gamepulse.steam import make_client


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gamepulse", description="Steam data collectors.")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--games", type=Path, default=Path("games.toml"), help="game list (TOML)")
    common.add_argument("--data-dir", type=Path, default=Path("data"), help="where raw data goes")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ccu", parents=[common], help="current player counts")
    news = sub.add_parser("news", parents=[common], help="news items not stored yet")
    news.add_argument(
        "--full",
        action="store_true",
        help="walk the whole history (first run, or after an interrupted one)",
    )
    sub.add_parser("reviews", parents=[common], help="review histogram snapshot")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        games = load_games(args.games)
    except (OSError, ValueError, KeyError) as exc:
        print(f"gamepulse: cannot load games from {args.games}: {exc}", file=sys.stderr)
        return 1
    with make_client() as client:
        if args.command == "ccu":
            succeeded = collect_ccu.run(client, games, args.data_dir)
        elif args.command == "news":
            succeeded = collect_news.run(client, games, args.data_dir, full=args.full)
        elif args.command == "reviews":
            succeeded = collect_reviews.run(client, games, args.data_dir)
        else:  # pragma: no cover - argparse rejects unknown commands
            raise AssertionError(args.command)
    return 0 if succeeded else 1


if __name__ == "__main__":
    sys.exit(main())
