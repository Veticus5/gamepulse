"""Build the analytical tables with dbt and publish the anomalies.

The dbt project in ``gamepulse/warehouse`` reads the raw files and writes
its tables to ``data/warehouse/gamepulse.duckdb``. Only one process can
have that file open for writing, so the finished ``anomalies`` table is
also copied to ``data/derived/anomalies.parquet``, which the interface and
the agent read instead.
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import duckdb

log = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).parent / "warehouse"


def warehouse_path(data_dir: Path) -> Path:
    return data_dir / "warehouse" / "gamepulse.duckdb"


def anomalies_path(data_dir: Path) -> Path:
    return data_dir / "derived" / "anomalies.parquet"


def episodes_path(data_dir: Path) -> Path:
    return data_dir / "derived" / "anomaly_episodes.parquet"


def run(data_dir: Path) -> int:
    """Run all dbt models and tests; return the number of anomalies found."""
    data_dir = data_dir.resolve()
    out = anomalies_path(data_dir)
    if not any((data_dir / "raw" / "review_histogram").glob("*.jsonl")):
        log.warning("model: no review data in %s yet", data_dir)
        out.unlink(missing_ok=True)
        episodes_path(data_dir).unlink(missing_ok=True)
        return 0

    db = warehouse_path(data_dir)
    db.parent.mkdir(parents=True, exist_ok=True)
    # A separate process: dbt keeps the database open for as long as it lives,
    # and the copy below needs the file to itself.
    done = subprocess.run(
        [
            sys.executable, "-m", "dbt.cli.main",
            "--quiet",
            "--no-send-anonymous-usage-stats",
            "--no-version-check",
            "build",
            "--project-dir", str(PROJECT_DIR),
            "--profiles-dir", str(PROJECT_DIR),
            "--target-path", str(db.parent / "target"),
            "--log-path", str(db.parent / "logs"),
            "--vars", json.dumps({"raw_dir": str(data_dir / "raw")}),
        ],
        env={**os.environ, "GAMEPULSE_DUCKDB": str(db), "DO_NOT_TRACK": "1"},
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise RuntimeError(f"dbt build failed:\n{(done.stdout + done.stderr).strip()[-2000:]}")

    out.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db), read_only=True) as con:
        for table, path in (("anomalies", out), ("anomaly_episodes", episodes_path(data_dir))):
            tmp = path.with_suffix(".tmp")
            con.execute(f"COPY (SELECT * FROM {table} ORDER BY period_start, appid, grain, 1) TO '{tmp}' (FORMAT parquet)")
            tmp.replace(path)  # readers see either the old file or the new one, never half of it
        count = con.execute("SELECT count(*) FROM anomalies").fetchone()[0]
        episodes = con.execute("SELECT count(*) FROM anomaly_episodes").fetchone()[0]
    log.info("model: %d anomalies in %d episodes", count, episodes)
    return count


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with duckdb.connect() as con:
        cursor = con.execute("SELECT * FROM read_parquet(?)", [str(path)])
        names = [d[0] for d in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]


def load_anomalies(data_dir: Path) -> list[dict]:
    """Published anomalies (one per period and kind), oldest first; empty when the models have not run."""
    return _load(anomalies_path(data_dir))


def load_episodes(data_dir: Path) -> list[dict]:
    """Published episodes (runs of neighbouring unusual periods), oldest first."""
    return _load(episodes_path(data_dir))
