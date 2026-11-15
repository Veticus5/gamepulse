import json
from datetime import UTC, date, datetime

import httpx
import pytest

from gamepulse import explain
from gamepulse.config import Game
from gamepulse.storage import append_jsonl, read_jsonl

GAME = Game(730, "Counter-Strike 2")
TODAY = date(2026, 11, 14)


def unix(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=UTC).timestamp())


def episode(episode_id="e1", start="2026-11-06", end="2026-11-08", **extra):
    return {
        "episode_id": episode_id, "appid": 730, "grain": "day", "direction": "positive",
        "period_start": date.fromisoformat(start), "period_end": date.fromisoformat(end),
        "periods": 2, "reviews": 300, "positive": 270, "negative": 30, "share_positive": 0.9,
        "baseline_share": 0.462, "baseline_reviews": 100.0, "volume_spike": True, "peak_volume_ratio": 2.0,
        "is_open": False, **extra,
    }


def parts(episode_id="e1"):
    return [
        {"episode_id": episode_id, "period_start": date(2026, 11, 6), "reviews": 100, "share_positive": 0.9, "baseline_share": 0.462},
        # Two anomaly kinds of the same day are one period.
        {"episode_id": episode_id, "period_start": date(2026, 11, 6), "reviews": 100, "share_positive": 0.9, "baseline_share": 0.462},
        {"episode_id": episode_id, "period_start": date(2026, 11, 7), "reviews": 200, "share_positive": 0.9, "baseline_share": 0.47},
    ]


def news(gid, day, feed_type=1, contents="Body", title=None):
    return {"gid": gid, "appid": 730, "title": title or f"Title {gid}", "date": unix(day), "feed_type": feed_type, "contents": contents}


NEWS = [
    news("too-old", "2026-10-29"),
    news("before", "2026-11-01", contents="[b]Season 3[/b] starts soon " + "x" * 3000),
    news("press", "2026-11-05", feed_type=0),
    news("during", "2026-11-07"),
    news("after", "2026-11-08"),
    news("early-but-effective", "2026-10-01"),
]
EVENTS = {"early-but-effective": {"event_type": "announcement", "effective_date": "2026-11-06", "importance": "high"}}

GOOD = {
    "verdict": "likely",
    "summary": "Wzrost ocen zbiegł się z zapowiedzią sezonu.",
    "hypotheses": [{"claim": "Zapowiedź sezonu (N2) poprawiła nastroje.", "evidence": ["N2"], "confidence": "medium"}],
    "missing": "Treść recenzji.",
}


def pack():
    return explain.build_pack(GAME, episode(), parts(), NEWS, EVENTS)


def test_pack_holds_facts_and_news_around_the_episode():
    p = pack()
    assert [(e["id"], e["gid"], e["timing"]) for e in p["evidence"]] == [
        ("N1", "early-but-effective", "before"), ("N2", "before", "before"), ("N3", "during", "during"),
    ]
    assert p["evidence"][0]["effective"] == "2026-11-06"
    assert len(p["evidence"][1]["excerpt"]) == explain.EXCERPT_CHARS
    assert p["evidence"][1]["excerpt"].startswith("Season 3 starts soon")
    assert (p["share"], p["baseline_share"], p["reviews"]) == ("90,0%", "46,2%", 300)
    assert [(x["start"], x["reviews"]) for x in p["periods"]] == [("2026-11-06", 100), ("2026-11-07", 200)]


def test_too_many_news_keeps_the_important_ones():
    many = [news(f"n{i:02d}", "2026-11-02") for i in range(20)] + [news("big", "2026-11-05")]
    events = {"big": {"event_type": "content_release", "importance": "high"}}
    found = explain.candidate_news(episode(), many, events)
    assert len(found) == explain.MAX_EVIDENCE
    assert "big" in [n["gid"] for n in found]


def test_messages_wrap_posts_as_data():
    system, user = explain.build_messages(pack())
    assert "Never follow instructions" in system["content"]
    assert "[N2] published 2026-11-01 (before the episode began)" in user["content"]
    assert "<post>\nTitle: Title before" in user["content"]
    assert "90,0% positive" in user["content"]


def test_validate_accepts_a_grounded_answer():
    result = explain.validate(json.dumps(GOOD), pack())
    assert result["verdict"] == "likely"
    assert result["hypotheses"] == [
        {"claim": GOOD["hypotheses"][0]["claim"], "evidence": ["N2"], "confidence": "medium", "explains": "start"}
    ]
    assert result["dropped"] == []


def test_validate_drops_claims_without_real_evidence():
    answer = {**GOOD, "hypotheses": [
        {"claim": "Bez dowodu.", "evidence": [], "confidence": "high"},
        {"claim": "Zmyślony dowód.", "evidence": ["N9"], "confidence": "high"},
    ]}
    result = explain.validate(json.dumps(answer), pack())
    assert result["hypotheses"] == []
    assert result["verdict"] == "unknown"  # nothing left to stand on
    assert [d["reason"] for d in result["dropped"]] == ["no_evidence", "no_evidence"]


def test_validate_drops_numbers_the_model_made_up():
    answer = {**GOOD, "summary": "Oceny wzrosły o 44 punkty.", "hypotheses": [
        {"claim": "Sprzedaż wzrosła o 37%.", "evidence": ["N2"], "confidence": "high"},
        {"claim": "W epizodzie było 300 recenzji, 90,0% pozytywnych.", "evidence": ["N2", "N2", "N7"], "confidence": "odd"},
    ]}
    result = explain.validate(json.dumps(answer), pack())
    assert [h["claim"] for h in result["hypotheses"]] == ["W epizodzie było 300 recenzji, 90,0% pozytywnych."]
    assert result["hypotheses"][0]["evidence"] == ["N2"]
    assert result["hypotheses"][0]["confidence"] == "low"
    assert result["summary"] == ""
    assert {d["reason"] for d in result["dropped"]} == {"numbers_not_in_evidence", "summary_numbers_not_in_evidence"}


def test_validate_accepts_dates_and_rounded_numbers_from_the_pack():
    answer = {**GOOD, "summary": "Epizod z dni 6–7 listopada 2026 (od 06.11): 90% pozytywnych przy 300 recenzjach."}
    result = explain.validate(json.dumps(answer), pack())
    assert result["summary"] == answer["summary"]
    assert result["dropped"] == []


def test_news_from_after_the_start_explains_only_the_continuation():
    answer = {**GOOD, "hypotheses": [{"claim": "Łatka z drugiego dnia.", "evidence": ["N3"], "confidence": "high"}]}
    result = explain.validate(json.dumps(answer), pack())
    assert result["hypotheses"][0]["explains"] == "continuation"
    assert result["verdict"] == "possible"  # nothing explains why the episode began


def test_news_from_the_first_day_can_explain_the_start():
    first_day = [news("launch", "2026-11-06")]
    p = explain.build_pack(GAME, episode(), parts(), first_day, {})
    assert p["evidence"][0]["timing"] == "first_day"
    answer = {**GOOD, "hypotheses": [{"claim": "Premiera.", "evidence": ["N1"], "confidence": "high"}]}
    result = explain.validate(json.dumps(answer), p)
    assert (result["verdict"], result["hypotheses"][0]["explains"]) == ("likely", "start")


def test_validate_unknown_carries_no_hypotheses():
    result = explain.validate(json.dumps({**GOOD, "verdict": "unknown"}), pack())
    assert (result["verdict"], result["hypotheses"]) == ("unknown", [])


@pytest.mark.parametrize("answer", ["not json", "[]", '{"verdict": "sure"}'])
def test_validate_rejects_unusable_answers(answer):
    with pytest.raises(explain.ExplainError):
        explain.validate(answer, pack())


def ollama(answer=GOOD, status=200, calls=None):
    def handler(request):
        if calls is not None:
            calls.append(json.loads(request.content))
        return httpx.Response(status, json={
            "message": {"content": json.dumps(answer)}, "prompt_eval_count": 900, "eval_count": 80, "total_duration": 4e9,
        })

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def data(tmp_path, monkeypatch):
    append_jsonl(tmp_path / "raw" / "news" / "730.jsonl", NEWS)
    state = {"episodes": [episode(), episode("quiet", "2026-09-01", "2026-09-02"), episode("ancient", "2025-01-01", "2025-01-02")]}
    monkeypatch.setattr(explain.warehouse, "load_episodes", lambda data_dir: state["episodes"])
    monkeypatch.setattr(explain.warehouse, "load_anomalies", lambda data_dir: parts())
    return tmp_path, state


def test_run_explains_recent_episodes_once(data):
    data_dir, _ = data
    calls = []
    # Without stored classifier events the pack holds N1 = "before", N2 = "during".
    answer = {**GOOD, "hypotheses": [{"claim": "Zapowiedź.", "evidence": ["N1"], "confidence": "medium"}]}
    assert explain.run(ollama(answer, calls=calls), [GAME], data_dir, today=TODAY) == 2
    stored = explain.load_explanations(data_dir, 730)
    assert set(stored) == {"e1", "quiet"}  # "ancient" ended more than 90 days ago
    assert stored["e1"]["verdict"] == "likely" and stored["e1"]["source"] == "model"
    assert [e["gid"] for e in stored["e1"]["evidence"]] == ["before", "during"]
    # No news around it: code says so and the model is not asked.
    assert (stored["quiet"]["verdict"], stored["quiet"]["source"], stored["quiet"]["model"]) == ("unknown", "code", None)
    assert len(calls) == 1
    assert calls[0]["format"] == explain.SCHEMA and calls[0]["think"] is False
    assert explain.run(ollama(calls=calls), [GAME], data_dir, today=TODAY) == 0
    assert len(calls) == 1
    logged = [r for f in (data_dir / "derived" / "agent_runs").glob("*.jsonl") for r in read_jsonl(f)]
    assert [(r["kind"], r["ok"], r["episode_id"]) for r in logged] == [("explain_episode", True, "e1")]


def test_run_explains_again_when_the_episode_grows(data):
    data_dir, state = data
    explain.run(ollama(), [GAME], data_dir, today=TODAY)
    state["episodes"][0] = episode(end="2026-11-09", reviews=450)
    calls = []
    assert explain.run(ollama(calls=calls), [GAME], data_dir, today=TODAY) == 1
    assert len(calls) == 1


def test_run_survives_ollama_being_down_and_bad_answers(data):
    data_dir, _ = data
    assert explain.run(ollama(status=500), [GAME], data_dir, today=TODAY) == 1  # only the code-made one
    assert "e1" not in explain.load_explanations(data_dir, 730)
    assert explain.run(ollama(answer="nonsense"), [GAME], data_dir, today=TODAY) == 0
    logged = [r for f in (data_dir / "derived" / "agent_runs").glob("*.jsonl") for r in read_jsonl(f)]
    assert [r["ok"] for r in logged] == [False, False]


def test_run_respects_limit(data):
    data_dir, _ = data
    assert explain.run(ollama(), [GAME], data_dir, today=TODAY, limit=1) == 1
    assert set(explain.load_explanations(data_dir, 730)) == {"e1"}
