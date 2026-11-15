"""Measuring the explaining agent against a person's judgement.

A person reads an explanation next to its evidence and says whether it
holds. Ratings go to ``eval/explanation_ratings.jsonl``; ``summarise``
then shows how often each verdict of the agent was right.

A rating belongs to one version of an explanation (its input hash): when
the agent explains the episode again from new evidence, the old rating
does not carry over.
"""

from pathlib import Path

from gamepulse import explain, model as warehouse
from gamepulse.config import Game
from gamepulse.storage import append_jsonl, read_jsonl, utc_now_iso

RATINGS_FILE = "explanation_ratings.jsonl"
RATINGS = ("correct", "partly", "wrong", "cannot_tell")


def current_explanations(games: list[Game], data_dir: Path) -> list[dict]:
    """The latest explanation of every episode that still exists, newest episode first."""
    episodes = {e["episode_id"]: e for e in warehouse.load_episodes(data_dir)}
    found = []
    for game in games:
        for episode_id, row in explain.load_explanations(data_dir, game.appid).items():
            if episode_id in episodes:
                found.append((episodes[episode_id]["period_end"], episode_id, row))
    found.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [row for _, _, row in found]


def _key(row: dict) -> tuple:
    return row.get("episode_id"), row.get("input_hash")


def load_ratings(eval_dir: Path) -> dict[tuple, dict]:
    """Latest rating per explanation version."""
    return {_key(row): row for row in read_jsonl(eval_dir / RATINGS_FILE) if row.get("rating") in RATINGS}


def save_rating(eval_dir: Path, explanation: dict, rating: str, note: str = "") -> None:
    if rating not in RATINGS:
        raise ValueError(f"unknown rating: {rating}")
    append_jsonl(eval_dir / RATINGS_FILE, [{
        "episode_id": explanation["episode_id"],
        "appid": explanation["appid"],
        "input_hash": explanation.get("input_hash"),
        "prompt_version": explanation.get("prompt_version"),
        "model": explanation.get("model"),
        "verdict": explanation.get("verdict"),
        "rating": rating,
        "note": note.strip()[:1000],
        "rated_at": utc_now_iso(),
    }])


def undo_last_rating(eval_dir: Path) -> str | None:
    """Drop the most recent rating so that explanation can be rated again.

    Removes every saved rating of that explanation version and returns the
    episode id, or None when there is nothing to undo.
    """
    path = eval_dir / RATINGS_FILE
    rows = [row for row in read_jsonl(path) if "episode_id" in row]
    if not rows:
        return None
    last = _key(rows[-1])
    kept = [row for row in rows if _key(row) != last]
    tmp = path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    append_jsonl(tmp, kept)
    if kept:
        tmp.replace(path)
    else:
        path.unlink()
    return last[0]


def pending(explanations: list[dict], ratings: dict[tuple, dict]) -> list[dict]:
    """Explanations made by the model that have no rating yet."""
    return [e for e in explanations if e.get("source") == "model" and _key(e) not in ratings]


def summarise(explanations: list[dict], ratings: dict[tuple, dict]) -> dict:
    """Ratings of the current explanations, split by the agent's verdict."""
    table: dict[str, dict[str, int]] = {}
    rated = 0
    for explanation in explanations:
        rating = ratings.get(_key(explanation))
        if explanation.get("source") != "model" or rating is None:
            continue
        rated += 1
        row = table.setdefault(explanation.get("verdict") or "unknown", dict.fromkeys(RATINGS, 0))
        row[rating["rating"]] += 1
    return {
        "rated": rated,
        "to_rate": len(pending(explanations, ratings)),
        "by_verdict": table,
    }


def format_report(summary: dict) -> str:
    if not summary["rated"]:
        return "Brak ocenionych wyjaśnień. Oceń je na stronie interfejsu: #/rate"
    names = {"likely": "prawdopodobna", "possible": "możliwa", "unknown": "nieznana"}
    lines = [
        f"Ocenione wyjaśnienia: {summary['rated']}; do oceny: {summary['to_rate']}",
        "",
        f"{'werdykt agenta':<16}{'trafne':>8}{'częściowo':>11}{'błędne':>8}{'nie wiem':>10}",
    ]
    for verdict in ("likely", "possible", "unknown"):
        row = summary["by_verdict"].get(verdict)
        if row:
            lines.append(f"{names[verdict]:<16}{row['correct']:>8}{row['partly']:>11}{row['wrong']:>8}{row['cannot_tell']:>10}")
    likely = summary["by_verdict"].get("likely")
    if likely:
        judged = likely["correct"] + likely["partly"] + likely["wrong"]
        if judged:
            lines += ["", f"„Prawdopodobna przyczyna” okazała się trafna w {likely['correct']} z {judged} ocenionych "
                          f"({likely['correct'] / judged:.0%}); z częściowo trafnymi: {(likely['correct'] + likely['partly']) / judged:.0%}."]
    return "\n".join(lines)
