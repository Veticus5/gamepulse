"""Write demo/data.js: a snapshot of a few games for the stand-alone demo page.

The demo page is plain files that open straight from disk, so its data is a
script that sets one global. Run from the project root after `gamepulse model`:

    uv run python demo/build_data.py

Only what the page shows is exported: daily and monthly numbers, the agent's
explanations, news titles and a few short review quotes per explanation.
Full review texts and anything about reviewers stay out.
"""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
TABLES = ROOT / "data" / "derived" / "tables"
OUT = Path(__file__).resolve().parent / "data.js"

# Games with a story worth showing, in display order.
GAMES = [553850, 1867240, 238960, 381210, 3240220, 2868840]
EPISODE_DAYS = 400
QUOTES_PER_CAUSE = 3
QUOTE_CHARS = 220


def table(name: str) -> str:
    return f"read_parquet('{TABLES / (name + '.parquet')}')"


def ms(value) -> int:
    if isinstance(value, datetime):
        return int(value.replace(tzinfo=UTC).timestamp() * 1000)
    return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp() * 1000)


def rows(con, sql: str, params=()) -> list[dict]:
    cursor = con.execute(sql, list(params))
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def causes(explanation: dict, urls: dict[str, dict]) -> list[dict]:
    evidence = {item["id"]: item for item in json.loads(explanation["evidence"] or "[]")}
    out = []
    for hypothesis in json.loads(explanation["hypotheses"] or "[]"):
        cited = [evidence[i] for i in hypothesis.get("evidence", []) if i in evidence]
        quotes = [
            {"text": item["excerpt"][:QUOTE_CHARS].rstrip() + ("…" if len(item["excerpt"]) > QUOTE_CHARS else ""),
             "positive": bool(item.get("voted_up")), "hours": item.get("playtime_hours"),
             "language": item.get("language")}
            for item in cited if item.get("kind") == "review" and item.get("excerpt")
        ]
        # English and Polish quotes first: the people this demo is shown to can read them.
        quotes.sort(key=lambda q: q["language"] not in ("english", "polish"))
        posts = [
            {"title": item.get("title"), "url": urls.get(item.get("gid"), {}).get("url"),
             "source": urls.get(item.get("gid"), {}).get("feed_label"), "press": item.get("kind") == "press",
             "date": item.get("published")}
            for item in cited if item.get("kind", "news") in ("news", "press") and item.get("title")
            # Steam lists press in every language; keep what the audience can read.
            and (item.get("kind") != "press" or item["title"].isascii())
        ]
        discounts = [
            {"percent": item.get("percent"), "from": item.get("published"), "to": item.get("until")}
            for item in cited if item.get("kind") == "discount"
        ]
        out.append({
            "claim": hypothesis.get("claim"),
            "reviews_cited": sum(1 for item in cited if item.get("kind") == "review"),
            "quotes": quotes[:QUOTES_PER_CAUSE],
            "posts": posts[:3],
            "discounts": discounts,
        })
    return out


def game(con, appid: int, today: date) -> dict:
    info = rows(con, f"select * from {table('games')} where appid = ?", [appid])[0]
    players = con.execute(
        f"""
        select epoch_ms(time_bucket(interval 1 hour, measured_at)), cast(round(avg(player_count)) as bigint)
        from {table('player_counts')} where appid = ? group by 1 order by 1
        """, [appid]).fetchall()
    periods = rows(con, f"""
        select grain, period_start, positive, negative from {table('review_periods')}
        where appid = ? and reviews > 0 order by period_start
        """, [appid])
    long = [[ms(p["period_start"]), p["positive"], p["negative"]] for p in periods
            if p["grain"] != "day" and p["period_start"] >= today - timedelta(days=760)]
    days = [p for p in periods if p["grain"] == "day" and p["period_start"] > today - timedelta(days=31)]
    up, down = sum(p["positive"] for p in days), sum(p["negative"] for p in days)
    urls = {r["gid"]: r for r in rows(con, f"select gid, url, feed_label from {table('news')} where appid = ?", [appid])}
    episodes = []
    for e in rows(con, f"""
        select * from {table('episode_explanations')}
        where appid = ? and period_end >= ? order by period_start desc
        """, [appid, today - timedelta(days=EPISODE_DAYS)]):
        episodes.append({
            "id": e["episode_id"],
            "from": ms(e["period_start"]),
            "to": ms(e["period_end"]),
            "direction": e["direction"],
            "reviews": int(e["reviews"]),
            "share": round(e["share_positive"] * 100, 1),
            "usual": round(e["baseline_share"] * 100, 1),
            "verdict": e["verdict"],
            "summary": e["summary"],
            "missing": e["missing"],
            "causes": causes(e, urls) if e["is_explained"] else [],
        })
    news = rows(con, f"""
        select title, url, published_at, label_summary, event_type from {table('news')}
        where appid = ? and is_official order by published_at desc limit 4
        """, [appid])
    return {
        "appid": appid,
        "name": info["name"],
        "image": info["header_image"] or f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg",
        "developers": info["developers"] or [],
        "genres": (info["genres"] or [])[:3],
        "players_now": info["players_now"],
        "players_peak": info["players_peak_24h"],
        "reviews_30d": {"positive": up, "negative": down},
        "players": [[int(t), int(v)] for t, v in players],
        "reviews": long,
        "reviews_grain": next((p["grain"] for p in periods if p["grain"] != "day"), "month"),
        "episodes": episodes,
        "news": [{"title": n["title"], "url": n["url"], "date": ms(n["published_at"]),
                  "summary": n["label_summary"], "type": n["event_type"]} for n in news],
    }


def main() -> None:
    with duckdb.connect() as con:
        newest = con.execute(f"select max(measured_at) from {table('player_counts')}").fetchone()[0]
        today = newest.date()
        data = {"generated": ms(newest), "games": [game(con, appid, today) for appid in GAMES]}
    OUT.write_text("window.GAMEPULSE_DEMO = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n")
    print(f"{OUT}: {OUT.stat().st_size // 1024} KB, {len(data['games'])} games, "
          f"{sum(len(g['episodes']) for g in data['games'])} episodes")


if __name__ == "__main__":
    main()
