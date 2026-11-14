"""Measuring the news classifier against hand-made labels.

``eval/news_sample.jsonl`` is a fixed random sample of official news.
A person labels it (through the interface, without seeing the model's
answer) into ``eval/news_labels.jsonl``. ``score`` then compares the two.
"""

import random
import time
from pathlib import Path

import httpx

from gamepulse import classify
from gamepulse.config import Game
from gamepulse.storage import append_jsonl, read_jsonl, utc_now_iso

SAMPLE_FILE = "news_sample.jsonl"
LABELS_FILE = "news_labels.jsonl"


def draw_sample(games: list[Game], data_dir: Path, *, size: int, since_days: int, seed: int = 42) -> list[dict]:
    """Pick ``size`` official news items, spread evenly across games."""
    cutoff = time.time() - since_days * 86400
    rng = random.Random(seed)
    pools = []
    seen: set = set()
    for game in games:
        items = [
            {"gid": item["gid"], "appid": game.appid}
            for item in read_jsonl(data_dir / "raw" / "news" / f"{game.appid}.jsonl")
            if item.get("feed_type") == 1
            and isinstance(item.get("date"), int)
            and item["date"] >= cutoff
            and item.get("gid") not in seen
        ]
        seen.update(item["gid"] for item in items)  # the same post can appear under two games
        rng.shuffle(items)
        if items:
            pools.append(items)
    sample = []
    while pools and len(sample) < size:  # round-robin so big games do not crowd out small ones
        for pool in list(pools):
            if len(sample) >= size:
                break
            sample.append(pool.pop())
            if not pool:
                pools.remove(pool)
    rng.shuffle(sample)
    return sample


def write_sample(eval_dir: Path, sample: list[dict]) -> Path:
    path = eval_dir / SAMPLE_FILE
    if path.exists():
        raise FileExistsError(f"{path} already exists; labels refer to it, so it is not overwritten")
    append_jsonl(path, sample)
    return path


def load_sample(eval_dir: Path) -> list[dict]:
    return read_jsonl(eval_dir / SAMPLE_FILE)


def load_labels(eval_dir: Path) -> dict[str, str | None]:
    """Latest label per news item; None means the labeller skipped it."""
    return {row["gid"]: row.get("event_type") for row in read_jsonl(eval_dir / LABELS_FILE) if "gid" in row}


def load_label_tags(eval_dir: Path) -> dict[str, list[str]]:
    """Secondary tags of the latest label per item. Labels made before tags
    existed carry none and are left out, so they do not count as "no tags"."""
    tags: dict[str, list[str]] = {}
    for row in read_jsonl(eval_dir / LABELS_FILE):
        if "gid" not in row:
            continue
        if isinstance(row.get("secondary_types"), list) and row.get("event_type"):
            tags[row["gid"]] = row["secondary_types"]
        else:
            tags.pop(row["gid"], None)
    return tags


def save_label(
    eval_dir: Path, gid: str, appid: int, event_type: str | None, secondary_types: list[str] | None = None
) -> None:
    row = {"gid": gid, "appid": appid, "event_type": event_type, "labeled_at": utc_now_iso()}
    if secondary_types is not None:
        row["secondary_types"] = secondary_types
    append_jsonl(eval_dir / LABELS_FILE, [row])


def score_tags(label_tags: dict[str, list[str]], predicted_tags: dict[str, list[str]]) -> dict:
    """How well the model's secondary tags match the labeller's, as sets."""
    pairs = [(set(tags), set(predicted_tags[gid])) for gid, tags in label_tags.items() if gid in predicted_tags]
    return {
        "compared": len(pairs),
        "identical": sum(1 for mine, model in pairs if mine == model),
        "labelled": sum(len(mine) for mine, _ in pairs),
        "found": sum(len(mine & model) for mine, model in pairs),
        "missed": sum(len(mine - model) for mine, model in pairs),
        "extra": sum(len(model - mine) for mine, model in pairs),
    }


def score(labels: dict[str, str | None], predictions: dict[str, str]) -> dict:
    """Accuracy and per-type precision and recall on items that have both."""
    pairs = [(gid, label, predictions[gid]) for gid, label in labels.items() if label and gid in predictions]
    correct = sum(1 for _, label, predicted in pairs if label == predicted)
    per_type = {}
    for event_type in classify.EVENT_TYPES:
        labelled = sum(1 for _, label, _ in pairs if label == event_type)
        predicted = sum(1 for _, _, pred in pairs if pred == event_type)
        hits = sum(1 for _, label, pred in pairs if label == pred == event_type)
        if labelled or predicted:
            per_type[event_type] = {
                "labelled": labelled,
                "predicted": predicted,
                "precision": round(hits / predicted, 3) if predicted else None,
                "recall": round(hits / labelled, 3) if labelled else None,
            }
    return {
        "compared": len(pairs),
        "correct": correct,
        "accuracy": round(correct / len(pairs), 3) if pairs else None,
        "skipped_by_labeller": sum(1 for label in labels.values() if not label),
        "missing_prediction": sum(1 for gid, label in labels.items() if label and gid not in predictions),
        "per_type": per_type,
        "disagreements": [
            {"gid": gid, "label": label, "predicted": predicted} for gid, label, predicted in pairs if label != predicted
        ],
    }


def run(client: httpx.Client, games: list[Game], data_dir: Path, eval_dir: Path, *, model: str) -> dict:
    """Classify any labelled item the model has not seen yet, then score."""
    labels = load_labels(eval_dir)
    appid_of = {row["gid"]: row["appid"] for row in load_sample(eval_dir)}
    by_appid = {game.appid: game for game in games}
    predictions: dict[str, str] = {}
    predicted_tags: dict[str, list[str]] = {}
    for appid in sorted({appid_of[gid] for gid in labels if gid in appid_of}):
        game = by_appid.get(appid)
        if game is None:
            continue
        wanted = {gid for gid, label in labels.items() if label and appid_of.get(gid) == appid}
        done = classify.load_events(data_dir, appid, model=model)
        missing = [
            item
            for item in read_jsonl(data_dir / "raw" / "news" / f"{appid}.jsonl")
            if item.get("gid") in wanted and item["gid"] not in done
        ]
        if missing:
            classify.classify_many(client, data_dir, game, missing, model)
            done = classify.load_events(data_dir, appid, model=model)
        predictions.update({gid: done[gid]["event_type"] for gid in wanted if gid in done})
        predicted_tags.update({gid: done[gid].get("secondary_types") or [] for gid in wanted if gid in done})
    result = score(labels, predictions)
    result["tags"] = score_tags(load_label_tags(eval_dir), predicted_tags)
    return result


def format_report(result: dict, titles: dict[str, str]) -> str:
    if not result["compared"]:
        return "Brak oznaczonych newsów do porównania. Oznacz próbkę na stronie interfejsu: #/label"
    lines = [
        f"Trafność typu wydarzenia: {result['correct']}/{result['compared']} = {result['accuracy']:.1%}",
        f"Pominięte przy oznaczaniu: {result['skipped_by_labeller']}; bez odpowiedzi modelu: {result['missing_prediction']}",
        "",
        f"{'typ':<18}{'oznaczone':>10}{'model':>8}{'precyzja':>10}{'czułość':>9}",
    ]
    for event_type, row in result["per_type"].items():
        fmt = lambda v: "—" if v is None else f"{v:.0%}"
        lines.append(f"{event_type:<18}{row['labelled']:>10}{row['predicted']:>8}{fmt(row['precision']):>10}{fmt(row['recall']):>9}")
    tags = result.get("tags")
    if tags and tags["compared"]:
        lines += [
            "",
            f"Tagi dodatkowe (na {tags['compared']} newsach oznaczonych z tagami): identyczny zestaw w {tags['identical']}",
            f"  Twoich tagów: {tags['labelled']}; model trafił {tags['found']}, pominął {tags['missed']}, dodał od siebie {tags['extra']}",
        ]
    if result["disagreements"]:
        lines += ["", "Rozbieżności (Twoja etykieta → model):"]
        for item in result["disagreements"]:
            lines.append(f"  {item['label']} → {item['predicted']}: {titles.get(item['gid'], item['gid'])[:80]}")
    return "\n".join(lines)
