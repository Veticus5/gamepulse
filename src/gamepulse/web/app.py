"""Local web interface: JSON API over the collected data plus static pages."""

import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from gamepulse import evaluate
from gamepulse.classify import EVENT_TYPES
from gamepulse.config import Game
from gamepulse.web.store import NEWS_KINDS, RANGES, Store

STATIC_DIR = Path(__file__).parent / "static"


class Label(BaseModel):
    gid: str
    event_type: str | None = None  # None = skipped by the labeller
    secondary_types: list[str] = []


def create_app(data_dir: Path, games: list[Game], eval_dir: Path = Path("eval")) -> FastAPI:
    app = FastAPI(title="GamePulse", docs_url=None, redoc_url=None, openapi_url=None)
    store = Store(data_dir, games)

    @app.get("/api/overview")
    def overview() -> dict:
        return store.overview()

    @app.get("/api/games/{appid}")
    def game(appid: int, range: str = "7d") -> dict:
        if range not in RANGES:
            raise HTTPException(400, f"range must be one of {', '.join(RANGES)}")
        result = store.game(appid, range, int(time.time() * 1000))
        if result is None:
            raise HTTPException(404, "game is not tracked")
        return result

    @app.get("/api/games/{appid}/episodes/{episode_id}")
    def episode(appid: int, episode_id: str) -> dict:
        result = store.episode(appid, episode_id)
        if result is None:
            raise HTTPException(404, "episode not found")
        return result

    @app.get("/api/games/{appid}/news")
    def news_list(
        appid: int,
        kind: str = "official",
        q: str = Query("", max_length=100),
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
    ) -> dict:
        if kind not in NEWS_KINDS:
            raise HTTPException(400, f"kind must be one of {', '.join(NEWS_KINDS)}")
        result = store.news_list(appid, kind, q, offset, limit)
        if result is None:
            raise HTTPException(404, "game is not tracked")
        return result

    @app.get("/api/games/{appid}/news/{gid}")
    def news_item(appid: int, gid: str) -> dict:
        result = store.news_item(appid, gid)
        if result is None:
            raise HTTPException(404, "news item not found")
        return result

    @app.get("/api/label/next")
    def label_next() -> dict:
        """The next sampled news item without a label. The model's answer is
        deliberately not included, so labels stay independent of it."""
        sample = evaluate.load_sample(eval_dir)
        labels = evaluate.load_labels(eval_dir)
        todo = [row for row in sample if row["gid"] not in labels]
        item = None
        if todo:
            found = store.news_item(todo[0]["appid"], todo[0]["gid"])
            if found is not None:
                item = {key: found[key] for key in ("gid", "title", "date_ms", "url", "contents")}
                item["game"] = next((g.name for g in games if g.appid == todo[0]["appid"]), "")
            else:  # the sampled item is gone from the data; do not get stuck on it
                evaluate.save_label(eval_dir, todo[0]["gid"], todo[0]["appid"], None)
                return label_next()
        return {"total": len(sample), "done": len(sample) - len(todo), "item": item, "event_types": list(EVENT_TYPES)}

    @app.post("/api/label")
    def label_save(label: Label) -> dict:
        appids = {row["gid"]: row["appid"] for row in evaluate.load_sample(eval_dir)}
        if label.gid not in appids:
            raise HTTPException(404, "news item is not in the sample")
        if label.event_type is not None and label.event_type not in EVENT_TYPES:
            raise HTTPException(400, "unknown event type")
        secondary = list(dict.fromkeys(label.secondary_types))
        if any(t not in EVENT_TYPES or t in ("other", label.event_type) for t in secondary):
            raise HTTPException(400, "secondary types must be known, and differ from the main type")
        evaluate.save_label(
            eval_dir, label.gid, appids[label.gid], label.event_type,
            secondary if label.event_type is not None else None,
        )
        return {"ok": True}

    @app.post("/api/label/undo")
    def label_undo() -> dict:
        return {"undone": evaluate.undo_last_label(eval_dir)}

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
