"""Pack the demo into single files that can be sent to anyone.

    uv run python demo/build_bundle.py

Writes two files to demo/dist/:

- gamepulse-demo.html: the whole demo in one file (styles, script, data and
  cover pictures inside). Open it in a browser; nothing else is needed.
- artifact.html: the same page without the outer document tags, for
  publishing as a hosted page.

Cover pictures are fetched once from Steam's image servers and kept in
demo/covers/, so later runs need no network.
"""

import base64
import json
import re
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"
COVERS = HERE / "covers"
PREFIX = "window.GAMEPULSE_DEMO = "


def cover(appid: int, url: str) -> str | None:
    """The cover as a data URI, or None when it cannot be fetched."""
    path = COVERS / f"{appid}.jpg"
    if not path.exists():
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "gamepulse-demo/0.1"})
            content = urllib.request.urlopen(request, timeout=20).read()
        except OSError as exc:
            print(f"cover {appid}: {exc}")
            return None
        COVERS.mkdir(exist_ok=True)
        path.write_bytes(content)
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()


def inline(script: str) -> str:
    # A closing script tag inside the text would end the inline script early.
    return script.replace("</", "<\\/")


def main() -> None:
    raw = (HERE / "data.js").read_text().strip()
    data = json.loads(raw[len(PREFIX):].rstrip(";"))
    for game in data["games"]:
        game["image"] = cover(game["appid"], game["image"]) or game["image"]
    data_js = PREFIX + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";"
    page = (HERE / "index.html").read_text()
    body = re.search(r"<body>(.*?)<script", page, re.S).group(1).strip()
    style = (HERE / "style.css").read_text()
    script = (HERE / "app.js").read_text()
    inside = (
        f"<style>\n{style}</style>\n{body}\n"
        f"<script>{inline(data_js)}</script>\n<script>\n{inline(script)}</script>\n"
    )
    DIST.mkdir(exist_ok=True)
    (DIST / "gamepulse-demo.html").write_text(
        '<!doctype html>\n<html lang="pl">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>GamePulse — demo</title>\n</head>\n<body>\n{inside}</body>\n</html>\n"
    )
    (DIST / "artifact.html").write_text(
        "<title>GamePulse Demo</title>\n"
        '<meta name="claude:viewport-fit-sides" content="cover">\n' + inside
    )
    for name in ("gamepulse-demo.html", "artifact.html"):
        print(f"{DIST / name}: {(DIST / name).stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
