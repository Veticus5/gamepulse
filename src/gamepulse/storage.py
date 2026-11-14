"""Append-only JSONL files for raw data."""

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ends_with_newline(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            if fh.tell() == 0:
                return True
            fh.seek(-1, 2)
            return fh.read(1) == b"\n"
    except FileNotFoundError:
        return True


def append_jsonl(path: Path, records: Iterable[dict]) -> int:
    """Append records as JSON lines; return how many were written.

    Everything goes out in a single write so that a concurrent run cannot
    interleave inside a line. A file left without a trailing newline by an
    interrupted run gets one first, so new records never join a broken line.
    """
    lines = [json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in records]
    if not lines:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(lines) + "\n"
    if not _ends_with_newline(path):
        payload = "\n" + payload
    with open(path, "ab") as fh:
        fh.write(payload.encode("utf-8"))
    return len(lines)


def read_jsonl(path: Path) -> list[dict]:
    """Read all records; a missing file is empty and broken lines are skipped."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    records = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records
