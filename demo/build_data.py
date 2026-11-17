"""Write demo/data.js: a snapshot of a few games for the stand-alone demo page.

The demo page is plain files that open straight from disk, so its data is a
script that sets one global. Run from the project root after `gamepulse model`:

    uv run python demo/build_data.py

Only what the page shows is exported: daily and monthly numbers, the agent's
explanations, news titles and a few short review quotes per explanation.
Full review texts and anything about reviewers stay out.
"""

import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb

from gamepulse.web.events import classify as rule_category

ROOT = Path(__file__).resolve().parent.parent
TABLES = ROOT / "data" / "derived" / "tables"
OUT = Path(__file__).resolve().parent / "data.js"

# Games with a story worth showing, in display order.
GAMES = [553850, 1867240, 238960, 381210, 3240220, 2868840]
EPISODE_DAYS = 400
QUOTES_PER_CAUSE = 3
QUOTE_CHARS = 220


# Store details fetched once from Steam's public store API (Polish names):
# game modes, systems, features, languages. See README for how to refresh.
STORE = json.loads((Path(__file__).resolve().parent / "store_details.json").read_text())
MODE_IDS = {1, 2, 9, 20, 24, 27, 36, 37, 38, 39, 47, 48, 49}

# Written by hand for the demo: what a page covers and which releases belong
# together. Only statements that hold for the Steam releases themselves.
NOTES = {
    3240220: {
        "scope": "Ta strona dotyczy wydania Enhanced z marca 2025 roku. Starsze wydanie, Legacy, ma na Steamie "
                 "osobną stronę, osobne oceny i osobną liczbę graczy. GTA Online wchodzi w skład obu wydań, "
                 "więc jego aktualizacje wpływają na oceny obu.",
        "related": [
            {"name": "Grand Theft Auto V Legacy", "note": "starsze wydanie na PC, nadal dostępne"},
            {"name": "GTA Online", "note": "tryb sieciowy, część obu wydań"},
        ],
    },
    238960: {"related": [{"name": "Path of Exile 2", "note": "osobna gra tego samego studia, rozwijana równolegle"}]},
    553850: {"related": [{"name": "HELLDIVERS", "note": "poprzednia część z 2015 roku"}]},
    2868840: {"related": [{"name": "Slay the Spire", "note": "poprzednia część z 2019 roku"}]},
}

# Editorial reviews are not collected yet. These rows only show how the
# section will look; the outlets do not exist and the scores mean nothing.
EXAMPLE_OUTLETS = [
    ("Poziom Wyżej", "8/10", "launch", "PC (Steam), wersja premierowa"),
    ("Kwadrans z Padem", "82/100", "launch", "PC (Steam), wersja premierowa"),
    ("Piksel i Spółka", "4/5", "later", "PC (Steam), stan z jesieni 2026"),
    ("Gry bez Tajemnic", "7/10", "later", "PC (Steam), stan z jesieni 2026"),
]

NEWS_GROUPS = [
    ("mods", re.compile(r"\bmod(s|ding|ded)?\b|workshop", re.I)),
    ("tech", re.compile(r"crash|\bbugs?\b|hot ?fix|outage|server (issue|problem|down)|downtime|performance|"
                        r"anti-?cheat|maintenance|rollback|known issues|broken|unplayable", re.I)),
    ("opinion", re.compile(r"\breviews?\b|opinion|impressions|hands-on|\bworth\b|ranked|\bbest\b|\bworst\b", re.I)),
    ("business", re.compile(r"\bsale\b|% off|discount|\bprice|free weekend|\bsold\b|\bsales\b|revenue|layoff|"
                            r"acqui|million|player count|steam charts|concurrent|bundle|record", re.I)),
]
LABEL_GROUPS = {"patch": "update", "content_release": "content", "in_game_event": "content",
                "sale": "business", "free_weekend": "business", "store_item": "business"}


def news_group(title: str, official: bool, event_type: str | None, tags) -> str:
    """Which filter a news item falls under. The classifier's label decides
    when there is one; otherwise simple rules on the title."""
    if event_type in LABEL_GROUPS:
        return LABEL_GROUPS[event_type]
    for name, pattern in NEWS_GROUPS:
        if pattern.search(title or "") and (name != "opinion" or not official):
            return name
    return {"patch": "update", "content_release": "content", "sale": "business"}.get(
        rule_category(title, official, list(tags or []))[0], "other")


def about(appid: int, info: dict) -> dict:
    """The small encyclopedia: what the store says about the game."""
    store = STORE.get(str(appid), {})
    categories = store.get("categories") or []
    names = [c["description"] for c in categories if not c["description"].startswith("#")]
    modes = [c["description"] for c in categories if c["id"] in MODE_IDS]
    features = [n for n in dict.fromkeys(names) if n not in modes]
    languages = [part.strip().rstrip("*") for part in
                 re.sub(r"<[^>]+>", "", (store.get("supported_languages") or "").split("<br>")[0]).split(",")]
    languages = [name for name in languages if name]
    systems = [label for key, label in (("windows", "Windows"), ("mac", "macOS"), ("linux", "Linux"))
               if (store.get("platforms") or {}).get(key)]
    note = NOTES.get(appid, {})
    return {
        "developers": info["developers"] or [],
        "publishers": info["publishers"] or [],
        "release": (store.get("release_date") or {}).get("date") or info["release_date_text"],
        "modes": modes,
        "systems": systems,
        "features": features[:8],
        "features_more": max(0, len(features) - 8),
        "languages": languages,
        "polish": "Polski" in languages,
        "dlc": len(store.get("dlc") or []),
        "scope": note.get("scope"),
        "related": note.get("related", []),
    }


def critic_reviews(appid: int, release_text: str | None) -> dict:
    store = STORE.get(str(appid), {})
    meta = store.get("metacritic") or None
    rows = [{"outlet": outlet, "score": score, "when": when, "covers": covers, "example": True}
            for outlet, score, when, covers in EXAMPLE_OUTLETS]
    return {"metacritic": {"score": meta["score"], "url": meta["url"].split("?")[0]} if meta else None, "rows": rows}


def price(con, appid: int, info: dict) -> dict:
    days = con.execute(
        f"select day, discount_percent from {table('prices_daily')} where appid = ? order by day", [appid]).fetchall()
    sales, run = [], None
    for day, percent in days:
        if percent > 0 and run and (day - run["last"]).days == 1 and run["percent"] == percent:
            run["last"] = day
        elif percent > 0:
            run = {"first": day, "last": day, "percent": int(percent)}
            sales.append(run)
        else:
            run = None
    return {
        "free": bool(STORE.get(str(appid), {}).get("is_free")),
        "currency": info["currency"],
        "final": info["final_price_cents"],
        "regular": info["regular_price_cents"],
        "discount": info["discount_percent"],
        "checked": ms(info["price_day"]) if info["price_day"] else None,
        "known_from": ms(days[0][0]) if days else None,
        "sales": [{"from": ms(r["first"]), "to": ms(r["last"]), "percent": r["percent"]} for r in sales][-8:],
    }


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
    news = [
        {"title": n["title"], "url": n["url"], "date": ms(n["published_at"]), "summary": n["label_summary"],
         "press": not n["is_official"], "source": "Twórcy gry" if n["is_official"] else n["feed_label"],
         "group": news_group(n["title"], n["is_official"], n["event_type"], n["tags"])}
        for n in rows(con, f"""
            select title, url, published_at, label_summary, event_type, is_official, feed_label, tags
            from {table('news')} where appid = ? order by published_at desc limit 400
            """, [appid])
        if n["title"] and (n["is_official"] or n["title"].isascii())
    ][:60]
    everything = [p for p in periods if p["grain"] != "day"]
    return {
        "appid": appid,
        "name": info["name"],
        "image": info["header_image"] or f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg",
        "developers": info["developers"] or [],
        "genres": (info["genres"] or [])[:3],
        "players_now": info["players_now"],
        "players_peak": info["players_peak_24h"],
        "reviews_30d": {"positive": up, "negative": down},
        "reviews_all": {"positive": sum(p["positive"] for p in everything),
                        "negative": sum(p["negative"] for p in everything)},
        "about": about(appid, info),
        "critics": critic_reviews(appid, info["release_date_text"]),
        "price": price(con, appid, info),
        "players": [[int(t), int(v)] for t, v in players],
        "reviews": long,
        "reviews_grain": next((p["grain"] for p in periods if p["grain"] != "day"), "month"),
        "episodes": episodes,
        "news": news,
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
