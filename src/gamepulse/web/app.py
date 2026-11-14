"""Local web interface: JSON API over the collected data plus static pages."""

import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from gamepulse.config import Game
from gamepulse.web.store import NEWS_KINDS, RANGES, Store

STATIC_DIR = Path(__file__).parent / "static"


def create_app(data_dir: Path, games: list[Game]) -> FastAPI:
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

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
