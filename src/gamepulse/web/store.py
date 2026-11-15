"""Read model for the interface: DuckDB over the raw JSONL files.

Tables live in memory and are reloaded when the files behind them change,
so the interface always shows what the collectors last wrote without
re-parsing everything on each request.
"""

import threading
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from gamepulse.config import Game
from gamepulse.storage import read_jsonl
from gamepulse.classify import priority_of
from gamepulse.model import anomalies_path, episodes_path
from gamepulse.web.events import classify as rule_category

MINUTE = 60_000
HOUR = 60 * MINUTE
DAY = 24 * HOUR

# Ranges of the player chart; "all" means since the first measurement.
RANGES = {"24h": DAY, "7d": 7 * DAY, "30d": 30 * DAY, "all": None}
HIGHLIGHT_WINDOW = 90 * DAY
NEWS_KINDS = ("official", "external", "all")
FIVEM_LIVE_SOURCE = "https://static.cfx.re/runtime/counts.json"
# A collector run is expected every 30 minutes (every 5 until 2026-11-15);
# anything longer than this
# between two runs counts as a gap (the computer was off, or Steam was down).
GAP_THRESHOLD = 45 * MINUTE
# How far before an episode its possible causes are looked for, per period length.
NEWS_LEAD = {"day": 7 * DAY, "week": 14 * DAY, "month": 14 * DAY}
EPISODE_NEWS_LIMIT = 40


def _sql_list(files: list[Path]) -> str:
    return "[" + ", ".join("'" + str(f).replace("'", "''") + "'" for f in files) + "]"


def _bucket_for(span_ms: int) -> int | None:
    """Bucket width for a chart covering ``span_ms``; None keeps raw points."""
    if span_ms <= 2 * DAY:
        return None
    if span_ms <= 45 * DAY:
        return HOUR
    return DAY


def _month_start(ms: int) -> int:
    moment = datetime.fromtimestamp(ms / 1000, UTC)
    return int(datetime(moment.year, moment.month, 1, tzinfo=UTC).timestamp() * 1000)


def _group_markers(items: list[dict], bucket) -> list[dict]:
    """One marker per bucket (a day or a month), most important item first."""
    groups: dict[int, list[dict]] = {}
    for item in items:
        groups.setdefault(bucket(item["event_ms"]), []).append(item)
    markers = []
    for start, group in sorted(groups.items()):
        group.sort(key=lambda n: (-n["priority"], -n["event_ms"]))
        markers.append(
            {
                "day_ms": start,
                "at_ms": group[0]["event_ms"],
                "count": len(group),
                "priority": group[0]["priority"],
                "items": group[:8],
            }
        )
    return markers


def _pct(up: int, down: int) -> float | None:
    total = up + down
    return round(100 * up / total, 1) if total else None


class Store:
    def __init__(self, data_dir: Path, games: list[Game]):
        self.data_dir = data_dir
        self.games = games
        self._by_appid = {g.appid: g for g in games}
        self._con = duckdb.connect(":memory:")
        self._lock = threading.Lock()
        self._signatures: dict[str, tuple] = {}
        self._reviews: dict[int, dict] = {}
        self._meta: dict[int, dict] = {}
        self._events: dict[str, dict] = {}
        self._episodes: dict[int, list[dict]] = {}

    # ------------------------------------------------------------ loading

    def _files(self, sub: str) -> list[Path]:
        return sorted((self.data_dir / "raw" / sub).glob("*.jsonl"))

    def _changed(self, name: str, files: list[Path]) -> bool:
        signature = tuple((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in files)
        if self._signatures.get(name) == signature:
            return False
        self._signatures[name] = signature
        return True

    def _load_table(self, table: str, files: list[Path], empty_schema: str, select: str) -> None:
        if not files:
            self._con.execute(f"CREATE OR REPLACE TABLE {table} ({empty_schema})")
            return
        self._con.execute(f"CREATE OR REPLACE TABLE {table} AS {select.format(files=_sql_list(files))}")

    def _refresh(self) -> None:
        files = self._files("ccu")
        if self._changed("ccu", files):
            self._load_table(
                "ccu",
                files,
                "ts_ms BIGINT, appid BIGINT, player_count BIGINT",
                """
                SELECT epoch_ms(CAST(ts AS TIMESTAMPTZ)) AS ts_ms, appid, player_count
                FROM read_json({files}, format='newline_delimited', ignore_errors=true,
                     columns={{ts:'VARCHAR', appid:'BIGINT', player_count:'BIGINT', ok:'BOOLEAN'}})
                WHERE ok AND player_count IS NOT NULL AND ts IS NOT NULL
                """,
            )
        files = self._files("fivem")
        if self._changed("fivem", files):
            self._load_table(
                "fivem",
                files,
                "ts_ms BIGINT, players BIGINT",
                f"""
                SELECT epoch_ms(CAST(ts AS TIMESTAMPTZ)) AS ts_ms, counts[1] AS players
                FROM read_json({{files}}, format='newline_delimited', ignore_errors=true,
                     columns={{{{ts:'VARCHAR', url:'VARCHAR', counts:'BIGINT[]', ok:'BOOLEAN'}}}})
                WHERE ok AND url = '{FIVEM_LIVE_SOURCE}' AND counts[1] IS NOT NULL
                """,
            )
        files = self._files("news")
        if self._changed("news", files):
            self._load_table(
                "news",
                files,
                "gid VARCHAR, appid BIGINT, title VARCHAR, date_ms BIGINT, feedlabel VARCHAR, "
                "feed_type BIGINT, url VARCHAR, author VARCHAR, contents VARCHAR, tags VARCHAR[]",
                """
                SELECT gid, any_value(appid) AS appid, any_value(title) AS title,
                       any_value(date) * 1000 AS date_ms, any_value(feedlabel) AS feedlabel,
                       any_value(feed_type) AS feed_type, any_value(url) AS url,
                       any_value(author) AS author, any_value(contents) AS contents,
                       any_value(tags) AS tags
                FROM read_json({files}, format='newline_delimited', ignore_errors=true,
                     columns={{gid:'VARCHAR', appid:'BIGINT', title:'VARCHAR', date:'BIGINT',
                              feedlabel:'VARCHAR', feed_type:'BIGINT', url:'VARCHAR',
                              author:'VARCHAR', contents:'VARCHAR', tags:'VARCHAR[]'}})
                WHERE gid IS NOT NULL AND date IS NOT NULL AND appid IS NOT NULL
                GROUP BY gid
                """,
            )
        files = self._files("review_histogram")
        if self._changed("reviews", files):
            self._reviews = self._latest_snapshots(files, "results")
        files = sorted((self.data_dir / "derived" / "news_events").glob("*.jsonl"))
        if self._changed("events", files):
            # Later lines win, so a re-classification replaces the earlier label.
            self._events = {row.get("gid"): row for path in files for row in read_jsonl(path)}
        paths = [p for p in (episodes_path(self.data_dir), anomalies_path(self.data_dir)) if p.exists()]
        if self._changed("episodes", paths):
            self._episodes = self._load_episodes(*paths) if len(paths) == 2 else {}
        files = self._files("appdetails")
        if self._changed("meta", files):
            self._meta = self._latest_snapshots(files, "details")

    def _load_episodes(self, episodes: Path, anomalies: Path) -> dict[int, list[dict]]:
        """Episodes per game, newest first, each with its periods in order."""
        parts: dict[str, list[dict]] = {}
        for episode_id, start_ms, end_ms, reviews, share, baseline_share, ratio, spike in self._con.execute(
            """
            SELECT episode_id, epoch_ms(period_start::TIMESTAMP), epoch_ms(period_end::TIMESTAMP),
                   any_value(reviews)::BIGINT, any_value(share_positive)::DOUBLE, any_value(baseline_share)::DOUBLE,
                   any_value(volume_ratio)::DOUBLE, bool_or(kind = 'review_volume_spike')
            FROM read_parquet(?) GROUP BY ALL ORDER BY 2
            """,
            [str(anomalies)],
        ).fetchall():
            parts.setdefault(episode_id, []).append({
                "start_ms": start_ms, "end_ms": end_ms, "reviews": reviews, "share": round(share, 4),
                "baseline_share": round(baseline_share, 4), "volume_ratio": round(ratio, 2), "volume_spike": spike,
            })
        by_game: dict[int, list[dict]] = {}
        for row in self._con.execute(
            """
            SELECT episode_id, appid, grain, direction, epoch_ms(period_start::TIMESTAMP),
                   epoch_ms(period_end::TIMESTAMP), periods::BIGINT, reviews::BIGINT, positive::BIGINT,
                   negative::BIGINT, share_positive::DOUBLE, baseline_share::DOUBLE, baseline_reviews::DOUBLE,
                   volume_spike, peak_volume_ratio::DOUBLE, is_open
            FROM read_parquet(?) ORDER BY period_start DESC, grain
            """,
            [str(episodes)],
        ).fetchall():
            by_game.setdefault(row[1], []).append({
                "id": row[0], "grain": row[2], "direction": row[3], "start_ms": row[4], "end_ms": row[5],
                "periods": row[6], "reviews": row[7], "positive": row[8], "negative": row[9],
                "share": round(row[10], 4), "baseline_share": round(row[11], 4),
                "baseline_reviews": round(row[12], 1), "volume_spike": row[13],
                "peak_volume_ratio": round(row[14], 2), "is_open": row[15], "parts": parts.get(row[0], []),
            })
        return by_game

    def episode(self, appid: int, episode_id: str) -> dict | None:
        """One episode with the official news around it: the evidence a
        person (and later the agent) looks at first. Listing news here says
        nothing about cause."""
        if appid not in self._by_appid:
            return None
        with self._lock:
            self._refresh()
            found = next((e for e in self._episodes.get(appid, []) if e["id"] == episode_id), None)
            if found is None:
                return None
            since = found["start_ms"] - NEWS_LEAD[found["grain"]]
            news = [
                self._news_dict(*row)
                for row in self._rows(
                    "SELECT gid, title, date_ms, feed_type, feedlabel, url, tags FROM news "
                    "WHERE appid = ? AND feed_type = 1 ORDER BY date_ms",
                    [appid],
                )
            ]
        # Published in the window, or taking effect in it: an announcement
        # made weeks earlier still belongs next to the episode it may explain.
        end = found["end_ms"]
        nearby = [n for n in news if since <= n["date_ms"] < end or since <= n["event_ms"] < end]
        shown = sorted(sorted(nearby, key=lambda n: (-n["priority"], n["date_ms"]))[:EPISODE_NEWS_LIMIT],
                       key=lambda n: n["date_ms"])
        return {**found, "news_from_ms": since, "news_total": len(nearby), "news": shown}

    @staticmethod
    def _latest_snapshots(files: list[Path], key: str) -> dict[int, dict]:
        latest = {}
        for path in files:
            rows = [r for r in read_jsonl(path) if isinstance(r.get(key), dict)]
            if rows and path.stem.isdigit():
                latest[int(path.stem)] = rows[-1][key]
        return latest

    def _rows(self, sql: str, params: list | None = None) -> list[tuple]:
        return self._con.execute(sql, params or []).fetchall()

    # ------------------------------------------------------------ helpers

    def _meta_for(self, appid: int) -> dict:
        details = self._meta.get(appid, {})
        release = details.get("release_date") or {}
        return {
            "appid": appid,
            "name": self._by_appid[appid].name,
            "image": details.get("header_image")
            or f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg",
            "developers": details.get("developers") or [],
            "publishers": details.get("publishers") or [],
            "release_date": release.get("date") or None,
            "genres": [g.get("description") for g in details.get("genres") or [] if g.get("description")],
            "is_free": details.get("is_free"),
            "description": details.get("short_description") or None,
            "store_url": f"https://store.steampowered.com/app/{appid}/",
        }

    def _review_summary(self, appid: int) -> dict:
        results = self._reviews.get(appid, {})

        def total(rows):
            up = sum(int(r.get("recommendations_up") or 0) for r in rows or [])
            down = sum(int(r.get("recommendations_down") or 0) for r in rows or [])
            return {"up": up, "down": down, "pct": _pct(up, down)}

        return {"recent": total(results.get("recent")), "all": total(results.get("rollups"))}

    # ------------------------------------------------------------ queries

    def overview(self) -> dict:
        with self._lock:
            self._refresh()
            now = self._rows("SELECT max(ts_ms) FROM ccu")[0][0]
            latest = {
                appid: (players, ts)
                for appid, players, ts in self._rows(
                    "SELECT appid, arg_max(player_count, ts_ms), max(ts_ms) FROM ccu GROUP BY appid"
                )
            }
            day_ago = dict(
                self._rows(
                    """
                    WITH latest AS (SELECT appid, max(ts_ms) AS t FROM ccu GROUP BY appid)
                    SELECT c.appid, arg_min(c.player_count, abs(c.ts_ms - (l.t - ?)))
                    FROM ccu c JOIN latest l USING (appid)
                    WHERE abs(c.ts_ms - (l.t - ?)) <= ?
                    GROUP BY c.appid
                    """,
                    [DAY, DAY, 45 * MINUTE],
                )
            )
            sparks: dict[int, list] = {}
            if now is not None:
                for appid, bucket, value in self._rows(
                    """
                    SELECT appid, ts_ms - ts_ms % ? AS b, round(avg(player_count))
                    FROM ccu WHERE ts_ms >= ? GROUP BY appid, b ORDER BY appid, b
                    """,
                    [30 * MINUTE, now - DAY],
                ):
                    sparks.setdefault(appid, []).append([bucket, int(value)])
            last_news = {
                appid: {"title": title, "date_ms": date}
                for appid, title, date in self._rows(
                    "SELECT appid, arg_max(title, date_ms), max(date_ms) FROM news "
                    "WHERE feed_type = 1 GROUP BY appid"
                )
            }
            runs = [r[0] for r in self._rows(
                "SELECT DISTINCT ts_ms - ts_ms % ? AS run FROM ccu ORDER BY run", [5 * MINUTE]
            )]
            fivem_latest = self._rows("SELECT arg_max(players, ts_ms), max(ts_ms) FROM fivem")[0]
            fivem_spark = []
            if fivem_latest[1] is not None:
                fivem_spark = [
                    [b, int(v)]
                    for b, v in self._rows(
                        "SELECT ts_ms - ts_ms % ? AS b, round(avg(players)) FROM fivem "
                        "WHERE ts_ms >= ? GROUP BY b ORDER BY b",
                        [30 * MINUTE, fivem_latest[1] - DAY],
                    )
                ]

            games = []
            for game in self.games:
                players, ts = latest.get(game.appid, (None, None))
                before = day_ago.get(game.appid)
                change = None
                if players is not None and before:
                    change = round(100 * (players - before) / before, 1)
                games.append(
                    {
                        **self._meta_for(game.appid),
                        "players": players,
                        "players_ts": ts,
                        "change_24h": change,
                        "spark": sparks.get(game.appid, []),
                        "reviews": self._review_summary(game.appid),
                        "last_news": last_news.get(game.appid),
                    }
                )
            games.sort(key=lambda g: (g["players"] is None, -(g["players"] or 0)))

            recent_runs = [r for r in runs if now is not None and r >= now - DAY]
            gaps = sum(1 for a, b in zip(recent_runs, recent_runs[1:]) if b - a > GAP_THRESHOLD)
            return {
                "status": {
                    "first_ts": runs[0] if runs else None,
                    "last_ts": now,
                    "runs_24h": len(recent_runs),
                    "gaps_24h": gaps,
                },
                "games": games,
                "fivem": {
                    "players": fivem_latest[0],
                    "players_ts": fivem_latest[1],
                    "spark": fivem_spark,
                },
            }

    def _news_dict(self, gid, title, date, feed_type, feedlabel, url, tags) -> dict:
        official = feed_type == 1
        event = self._events.get(gid) if official else None
        if event:
            category, priority, source = event.get("event_type"), priority_of(event), "model"
        else:
            (category, priority), source = rule_category(title, official, tags), "rules"
        # Where the event sits on a time axis: the day it takes effect when
        # the classifier found one, otherwise the moment the post went out.
        event_ms = date
        effective = event.get("effective_date") if event else None
        if effective:
            try:
                event_ms = int(datetime.fromisoformat(effective).replace(tzinfo=UTC).timestamp() * 1000) + 12 * HOUR
            except ValueError:
                effective = None
        return {
            "gid": gid,
            "title": title,
            "date_ms": date,
            "event_ms": event_ms,
            "effective_date": effective,
            "official": official,
            "feedlabel": feedlabel,
            "url": url,
            "category": category,
            "priority": priority,
            "source": source,
            "summary": event.get("summary") if event else None,
            "secondary": list(event.get("secondary_types") or []) if event else [],
        }

    def game(self, appid: int, range_key: str, now_ms: int) -> dict | None:
        if appid not in self._by_appid or range_key not in RANGES:
            return None
        with self._lock:
            self._refresh()
            first_ccu, last_ccu = self._rows(
                "SELECT min(ts_ms), max(ts_ms) FROM ccu WHERE appid = ?", [appid]
            )[0]
            span = RANGES[range_key]
            since = now_ms - span if span is not None else (first_ccu or now_ms - 7 * DAY)
            # Never stretch the axis over time with no measurements: Steam has
            # no history, so everything before the first run would be empty.
            if first_ccu is not None and since < first_ccu:
                since = first_ccu

            bucket = _bucket_for(now_ms - since)
            if bucket is None:
                ccu = self._rows(
                    "SELECT ts_ms, player_count FROM ccu WHERE appid = ? AND ts_ms >= ? ORDER BY ts_ms",
                    [appid, since],
                )
            else:
                ccu = self._rows(
                    "SELECT ts_ms - ts_ms % ? AS b, round(avg(player_count)) FROM ccu "
                    "WHERE appid = ? AND ts_ms >= ? GROUP BY b ORDER BY b",
                    [bucket, appid, since],
                )
            peak_24h = self._rows(
                "SELECT max(player_count) FROM ccu WHERE appid = ? AND ts_ms >= ?",
                [appid, (last_ccu or now_ms) - DAY],
            )[0][0]

            columns = "gid, title, date_ms, feed_type, feedlabel, url, tags"
            everything = [
                self._news_dict(*row)
                for row in self._rows(
                    f"SELECT {columns} FROM news WHERE appid = ? AND feed_type = 1 ORDER BY date_ms",
                    [appid],
                )
            ]
            in_range = [n for n in everything if since <= n["event_ms"] <= now_ms]
            markers = _group_markers(in_range, lambda ms: ms - ms % DAY)

            # Markers for the review charts: only launches over the whole
            # history (per month), anything notable over the last 30 days (per day).
            review_markers = {
                "monthly": _group_markers(
                    [n for n in everything if n["priority"] >= 3 and n["event_ms"] <= now_ms], _month_start
                ),
                "daily": _group_markers(
                    [n for n in everything if n["priority"] >= 2 and now_ms - 31 * DAY <= n["event_ms"] <= now_ms],
                    lambda ms: ms - ms % DAY,
                ),
            }

            recent = [n for n in everything if n["date_ms"] >= now_ms - HIGHLIGHT_WINDOW]
            recent.sort(key=lambda n: (-n["priority"], -n["date_ms"]))
            highlights = sorted(recent[:5], key=lambda n: -n["date_ms"])
            classified = sum(1 for n in everything if n["source"] == "model")
            totals = dict(
                self._rows(
                    "SELECT feed_type = 1, count(*) FROM news WHERE appid = ? GROUP BY 1", [appid]
                )
            )

            results = self._reviews.get(appid, {})

            def review_points(rows):
                return [
                    [r["date"] * 1000, int(r.get("recommendations_up") or 0), int(r.get("recommendations_down") or 0)]
                    for r in rows or []
                    if isinstance(r.get("date"), int)
                ]

            return {
                "meta": self._meta_for(appid),
                "range": {"key": range_key, "from": since, "to": now_ms},
                "ccu": [[int(t), int(v)] for t, v in ccu],
                "ccu_bucket_ms": bucket,
                "ccu_first_ts": first_ccu,
                "peak_24h": peak_24h,
                "markers": markers,
                "review_markers": review_markers,
                "highlights": highlights,
                "news_totals": {
                    "official": totals.get(True, 0),
                    "external": totals.get(False, 0),
                    "classified": classified,
                },
                "reviews": {
                    "daily": review_points(results.get("recent")),
                    "monthly": review_points(results.get("rollups")),
                },
                "review_summary": self._review_summary(appid),
                "episodes": self._episodes.get(appid, []),
            }

    def news_list(self, appid: int, kind: str, query: str, offset: int, limit: int) -> dict | None:
        if appid not in self._by_appid or kind not in NEWS_KINDS:
            return None
        where = ["appid = ?"]
        params: list = [appid]
        if kind != "all":
            where.append("feed_type = 1" if kind == "official" else "feed_type <> 1")
        if query.strip():
            where.append("title ILIKE ? ESCAPE '\\'")
            escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.append(f"%{escaped}%")
        clause = " AND ".join(where)
        with self._lock:
            self._refresh()
            total = self._rows(f"SELECT count(*) FROM news WHERE {clause}", params)[0][0]
            rows = self._rows(
                f"SELECT gid, title, date_ms, feed_type, feedlabel, url, tags FROM news WHERE {clause} "
                "ORDER BY date_ms DESC, gid LIMIT ? OFFSET ?",
                [*params, limit, offset],
            )
        return {"total": total, "items": [self._news_dict(*row) for row in rows]}

    def news_item(self, appid: int, gid: str) -> dict | None:
        with self._lock:
            self._refresh()
            rows = self._rows(
                "SELECT title, date_ms, feed_type, feedlabel, url, author, contents, tags FROM news "
                "WHERE appid = ? AND gid = ?",
                [appid, gid],
            )
        if not rows:
            return None
        title, date, feed_type, feedlabel, url, author, contents, tags = rows[0]
        return {
            **self._news_dict(gid, title, date, feed_type, feedlabel, url, tags),
            "author": author,
            "contents": contents or "",
        }
