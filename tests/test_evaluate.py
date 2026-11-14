import time

import pytest
from fastapi.testclient import TestClient

from gamepulse import classify, evaluate
from gamepulse.config import Game
from gamepulse.storage import append_jsonl, read_jsonl
from gamepulse.web.app import create_app

GAMES = [Game(730, "Counter-Strike 2"), Game(570, "Dota 2")]
NOW = int(time.time())


@pytest.fixture
def data_dir(tmp_path):
    for appid, count in ((730, 40), (570, 3)):
        append_jsonl(tmp_path / "data" / "raw" / "news" / f"{appid}.jsonl", [
            {"gid": f"{appid}-{i}", "appid": appid, "title": f"T{i}", "date": NOW - i * 86400, "feed_type": 1, "contents": "body"}
            for i in range(count)
        ] + [{"gid": f"{appid}-press", "appid": appid, "title": "P", "date": NOW, "feed_type": 0}])
    return tmp_path / "data"


def test_sample_is_spread_across_games_and_repeatable(data_dir):
    first = evaluate.draw_sample(GAMES, data_dir, size=10, since_days=365)
    assert first == evaluate.draw_sample(GAMES, data_dir, size=10, since_days=365)
    assert len(first) == 10 and len({row["gid"] for row in first}) == 10
    assert sum(1 for row in first if row["appid"] == 570) == 3  # the small game is fully represented
    assert not any(row["gid"].endswith("press") for row in first)
    assert len(evaluate.draw_sample(GAMES, data_dir, size=10, since_days=5)) == 8  # 5 + 3 recent ones


def test_sample_file_is_never_overwritten(tmp_path):
    evaluate.write_sample(tmp_path, [{"gid": "a", "appid": 1}])
    with pytest.raises(FileExistsError):
        evaluate.write_sample(tmp_path, [{"gid": "b", "appid": 1}])


def test_score_accuracy_per_type_and_disagreements():
    labels = {"a": "patch", "b": "patch", "c": "sale", "d": None, "e": "community"}
    predictions = {"a": "patch", "b": "content_release", "c": "sale"}
    result = evaluate.score(labels, predictions)
    assert (result["compared"], result["correct"], result["accuracy"]) == (3, 2, 0.667)
    assert result["skipped_by_labeller"] == 1 and result["missing_prediction"] == 1
    assert result["per_type"]["patch"] == {"labelled": 2, "predicted": 1, "precision": 1.0, "recall": 0.5}
    assert result["per_type"]["content_release"] == {"labelled": 0, "predicted": 1, "precision": 0.0, "recall": None}
    assert result["disagreements"] == [{"gid": "b", "label": "patch", "predicted": "content_release"}]
    assert evaluate.score({}, {})["accuracy"] is None


def test_labelling_flow_hides_the_model_answer_and_lets_you_correct(data_dir, tmp_path):
    eval_dir = tmp_path / "eval"
    evaluate.write_sample(eval_dir, [{"gid": "730-1", "appid": 730}, {"gid": "570-2", "appid": 570}])
    append_jsonl(data_dir / "derived" / "news_events" / "730.jsonl",
                 [{"gid": "730-1", "appid": 730, "event_type": "patch", "importance": "low", "summary": "s"}])
    client = TestClient(create_app(data_dir, GAMES, eval_dir))
    first = client.get("/api/label/next").json()
    assert (first["total"], first["done"]) == (2, 0)
    assert first["item"]["gid"] == "730-1" and first["item"]["game"] == "Counter-Strike 2"
    assert set(first["item"]) == {"gid", "title", "date_ms", "url", "contents", "game"}  # no model label
    assert client.post("/api/label", json={"gid": "730-1", "event_type": "sale"}).status_code == 200
    assert client.post("/api/label", json={"gid": "730-1", "event_type": "bogus"}).status_code == 400
    assert client.post("/api/label", json={"gid": "nope", "event_type": "sale"}).status_code == 404
    assert client.get("/api/label/next").json()["item"]["gid"] == "570-2"
    assert client.post("/api/label", json={"gid": "570-2", "event_type": None}).status_code == 200
    done = client.get("/api/label/next").json()
    assert done["done"] == 2 and done["item"] is None
    client.post("/api/label", json={"gid": "730-1", "event_type": "patch"})  # a correction: the latest wins
    assert evaluate.load_labels(eval_dir) == {"730-1": "patch", "570-2": None}
    assert evaluate.load_label_tags(eval_dir) == {"730-1": []}
    ok = client.post("/api/label", json={"gid": "730-1", "event_type": "in_game_event", "secondary_types": ["store_item", "sale", "sale"]})
    assert ok.status_code == 200
    assert evaluate.load_label_tags(eval_dir) == {"730-1": ["store_item", "sale"]}
    for bad in (["in_game_event"], ["other"], ["bogus"]):
        assert client.post("/api/label", json={"gid": "730-1", "event_type": "in_game_event", "secondary_types": bad}).status_code == 400


def test_run_classifies_only_missing_labelled_items(data_dir, tmp_path, client_for):
    import httpx, json

    eval_dir = tmp_path / "eval"
    evaluate.write_sample(eval_dir, [{"gid": "730-1", "appid": 730}, {"gid": "730-2", "appid": 730}, {"gid": "570-0", "appid": 570}])
    evaluate.save_label(eval_dir, "730-1", 730, "patch")
    evaluate.save_label(eval_dir, "730-2", 730, "sale")
    evaluate.save_label(eval_dir, "570-0", 570, None)
    append_jsonl(data_dir / "derived" / "news_events" / "730.jsonl",
                 [{"gid": "730-1", "appid": 730, "event_type": "patch", "model": "m",
                   "prompt_version": classify.PROMPT_VERSION, "secondary_types": []}])
    calls = []

    def handler(request):
        calls.append(1)
        answer = {"event_type": "patch", "secondary_types": ["sale"], "effective_date": None, "summary": "s", "importance": "low", "confidence": 0.5}
        return httpx.Response(200, json={"message": {"content": json.dumps(answer)}})

    result = evaluate.run(client_for(handler), GAMES, data_dir, eval_dir, model="m")
    assert len(calls) == 1  # only 730-2: 730-1 was already classified, 570-0 was skipped
    assert (result["compared"], result["correct"]) == (2, 1)
    assert result["tags"]["compared"] == 0  # these labels were saved without tags
    assert "1/2" in evaluate.format_report(result, {"730-2": "Some title"}) and "Some title" in evaluate.format_report(result, {"730-2": "Some title"})


def test_score_tags_compares_sets_and_ignores_labels_without_tags(tmp_path):
    evaluate.save_label(tmp_path, "old", 1, "patch")  # labelled before tags existed
    evaluate.save_label(tmp_path, "a", 1, "in_game_event", ["store_item", "sale"])
    evaluate.save_label(tmp_path, "b", 1, "patch", [])
    evaluate.save_label(tmp_path, "c", 1, None, None)
    label_tags = evaluate.load_label_tags(tmp_path)
    assert label_tags == {"a": ["store_item", "sale"], "b": []}
    result = evaluate.score_tags(label_tags, {"a": ["sale", "community"], "b": [], "old": ["sale"]})
    assert result == {"compared": 2, "identical": 1, "labelled": 2, "found": 1, "missed": 1, "extra": 1}
