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


def _dump(record: dict) -> bytes:
    text = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError:
        # A lone surrogate (e.g. a cut emoji) cannot be UTF-8; escape instead.
        return json.dumps(record, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def append_jsonl(path: Path, records: Iterable[dict]) -> int:
    """Append records as JSON lines; return how many were written.

    Everything goes out in a single write so that a concurrent run cannot
    interleave inside a line. A file left without a trailing newline by an
    interrupted run gets one first, so new records never join a broken line.
    """
    lines = [_dump(r) for r in records]
    if not lines:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"\n".join(lines) + b"\n"
    if not _ends_with_newline(path):
        payload = b"\n" + payload
    with open(path, "ab") as fh:
        fh.write(payload)
    return len(lines)


def read_jsonl(path: Path) -> list[dict]:
    """Read all records; a missing file is empty and broken lines are skipped."""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return []
    records = []
    # Split on the newline byte only: str.splitlines() would also break on
    # U+2028, U+2029 and U+0085, which occur inside news text.
    for line in data.split(b"\n"):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records
