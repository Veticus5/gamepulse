"""Bring player counts collected by GitHub Actions onto this machine.

The workflow in ``.github/workflows/player-counts.yml`` appends its
measurements to the ``data`` branch of the repository. This copies those
files into ``data/raw`` next to the locally collected ones, under a
``gh-`` prefix so the two never write to the same file. The interface
reads every file in the folder, so nothing else has to know about it.
"""

import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

KINDS = ("ccu", "fivem", "prices")
PREFIX = "gh-"


class RemoteError(Exception):
    """Git could not fetch or read the data branch."""


def _git(repo_dir: Path, *args: str) -> bytes:
    try:
        done = subprocess.run(
            ["git", "-C", str(repo_dir), *args],
            capture_output=True,
            timeout=120,
            # Never stop to ask for a password: this runs from a timer.
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RemoteError(f"git {args[0]}: {exc}") from exc
    if done.returncode != 0:
        raise RemoteError(f"git {args[0]}: {done.stderr.decode(errors='replace').strip()[-300:]}")
    return done.stdout


def pull(repo_dir: Path, data_dir: Path, *, remote: str = "origin", branch: str = "data") -> int:
    """Fetch the data branch and copy its files; return how many changed."""
    ref = f"refs/remotes/{remote}/{branch}"
    _git(repo_dir, "fetch", "--quiet", remote, f"+refs/heads/{branch}:{ref}")
    changed = 0
    for line in _git(repo_dir, "ls-tree", "-r", "--name-only", ref, "raw/").decode().splitlines():
        parts = Path(line).parts
        if len(parts) != 3 or parts[1] not in KINDS or not parts[2].endswith(".jsonl"):
            continue
        content = _git(repo_dir, "show", f"{ref}:{line}")
        target = data_dir / "raw" / parts[1] / f"{PREFIX}{parts[2]}"
        if target.exists() and target.read_bytes() == content:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(content)
        tmp.replace(target)  # readers see the old file or the new one, never half
        changed += 1
    log.info("pull-remote: %d files updated", changed)
    return changed
