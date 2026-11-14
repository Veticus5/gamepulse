import httpx

from gamepulse import collect_fivem
from gamepulse.storage import read_jsonl


def rows(data_dir):
    files = sorted((data_dir / "raw" / "fivem").glob("*.jsonl"))
    return files, [r for f in files for r in read_jsonl(f)]


def test_run_stores_raw_counts_per_source(tmp_path, client_for):
    def handler(request):
        if request.url.host == "static.cfx.re":
            return httpx.Response(200, json=[255384, 0, 255384])
        return httpx.Response(200, json=[None, 297210, None])

    assert collect_fivem.run(client_for(handler), tmp_path, pause=0) == 2
    files, stored = rows(tmp_path)
    assert len(files) == 1
    assert files[0].stem == stored[0]["ts"][:10]
    by_url = {r["url"]: r for r in stored}
    assert set(by_url) == set(collect_fivem.SOURCES)
    assert by_url["https://static.cfx.re/runtime/counts.json"]["counts"] == [255384, 0, 255384]
    assert by_url["https://runtime.fivem.net/counts.json"]["counts"] == [None, 297210, None]
    assert all(r["ok"] is True and r["error"] is None for r in stored)


def test_run_records_failure_and_continues(tmp_path, client_for):
    def handler(request):
        if request.url.host == "static.cfx.re":
            return httpx.Response(503)
        return httpx.Response(200, json=[None, 297210, None])

    assert collect_fivem.run(client_for(handler), tmp_path, pause=0) == 1
    _, stored = rows(tmp_path)
    failed = [r for r in stored if not r["ok"]]
    assert len(failed) == 1
    assert failed[0]["counts"] is None
    assert failed[0]["error"]


def test_unexpected_shape_is_a_failure(tmp_path, client_for):
    handler = lambda request: httpx.Response(200, json={"players": 5})
    assert collect_fivem.run(client_for(handler), tmp_path, pause=0) == 0
    _, stored = rows(tmp_path)
    assert [r["ok"] for r in stored] == [False, False]


def test_html_body_is_a_failure(tmp_path, client_for):
    handler = lambda request: httpx.Response(200, text="<html></html>")
    assert collect_fivem.run(client_for(handler), tmp_path, pause=0) == 0
