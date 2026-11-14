"""Command line entry point: ``gamepulse <collector>|classify|model|eval-sample|eval-classifier|web``."""

import argparse
import fcntl
import logging
import sys
from pathlib import Path
from typing import IO

from gamepulse import classify, evaluate, model, collect_ccu, collect_fivem, collect_meta, collect_news, collect_reviews
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
    sub.add_parser("meta", parents=[steam], help="Steam store metadata snapshot")
    cls = sub.add_parser("classify", parents=[steam], help="label official news with the local model")
    cls.add_argument("--since-days", type=int, default=90, help="only news this recent (default 90)")
    cls.add_argument("--limit", type=int, default=None, help="classify at most this many items")
    cls.add_argument("--model", default=classify.DEFAULT_MODEL, help="Ollama model name")
    sample = sub.add_parser("eval-sample", parents=[steam], help="draw the news sample to label by hand")
    sample.add_argument("--size", type=int, default=100)
    sample.add_argument("--since-days", type=int, default=365)
    sample.add_argument("--add", action="store_true", help="append a fresh batch to the existing sample")
    ev = sub.add_parser("eval-classifier", parents=[steam], help="compare the model with hand-made labels")
    ev.add_argument("--model", default=classify.DEFAULT_MODEL, help="Ollama model name")
    for command in (sample, ev):
        command.add_argument("--eval-dir", type=Path, default=Path("eval"), help="where the sample and labels live")
    web = sub.add_parser("web", parents=[steam], help="local web interface")
    web.add_argument("--host", default="127.0.0.1", help="address to listen on")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--eval-dir", type=Path, default=Path("eval"), help="where the sample and labels live")
    sub.add_parser("model", parents=[data], help="build the dbt tables and find review anomalies")
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
    if args.command == "model":
        lock = _acquire_lock(args.data_dir, "model")
        if lock is None:
            logging.warning("model: another run is in progress, skipping this one")
            return 0
        with lock:
            try:
                count = model.run(args.data_dir)
            except RuntimeError as exc:
                print(f"gamepulse: {exc}", file=sys.stderr)
                return 1
        print(f"Anomalie w recenzjach: {count} (zapisane w {model.anomalies_path(args.data_dir)})")
        return 0
    if args.command != "fivem":
        try:
            games = load_games(args.games)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"gamepulse: cannot load games from {args.games}: {exc}", file=sys.stderr)
            return 1
    if args.command == "web":
        # Imported here so the collectors do not load the web stack.
        import uvicorn

        from gamepulse.web.app import create_app

        uvicorn.run(create_app(args.data_dir, games, args.eval_dir), host=args.host, port=args.port, log_level="warning")
        return 0
    if args.command == "eval-sample":
        if args.add:
            picked = evaluate.add_batch(games, args.data_dir, args.eval_dir, size=args.size, since_days=args.since_days)
            print(f"Dodano nową partię: {len(picked)} newsów do oznaczenia")
            return 0 if picked else 1
        try:
            picked = evaluate.draw_sample(games, args.data_dir, size=args.size, since_days=args.since_days)
            path = evaluate.write_sample(args.eval_dir, picked)
        except FileExistsError as exc:
            print(f"gamepulse: {exc} (użyj --add, żeby dodać nową partię)", file=sys.stderr)
            return 1
        print(f"{len(picked)} newsów zapisanych w {path}")
        return 0 if picked else 1
    if args.command == "eval-classifier":
        from gamepulse.storage import read_jsonl

        with make_client() as client:
            result = evaluate.run(client, games, args.data_dir, args.eval_dir, model=args.model)
        titles = {
            row.get("gid"): row.get("title") or ""
            for game in games
            for row in read_jsonl(args.data_dir / "raw" / "news" / f"{game.appid}.jsonl")
        }
        print(evaluate.format_report(result, titles))
        return 0 if result["compared"] else 1
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
        elif args.command == "classify":
            succeeded = classify.run(
                client, games, args.data_dir,
                since_days=args.since_days, limit=args.limit, model=args.model,
            )
        elif args.command == "meta":
            succeeded = collect_meta.run(client, games, args.data_dir)
        else:
            succeeded = collect_fivem.run(client, args.data_dir)
    return 0 if succeeded else 1

if __name__ == "__main__":
    sys.exit(main())
