import pytest

from gamepulse import rate


def explanation(episode_id, verdict="likely", source="model", input_hash="h1"):
    return {"episode_id": episode_id, "appid": 730, "input_hash": input_hash, "prompt_version": "e5",
            "model": "m", "verdict": verdict, "source": source}


def test_ratings_are_kept_per_explanation_version(tmp_path):
    first = explanation("e1")
    rate.save_rating(tmp_path, first, "wrong", "  nie o to chodziło  ")
    rate.save_rating(tmp_path, first, "partly")  # changed their mind: the later one counts
    ratings = rate.load_ratings(tmp_path)
    assert ratings[("e1", "h1")]["rating"] == "partly"
    assert ratings[("e1", "h1")]["verdict"] == "likely"
    explained_again = explanation("e1", input_hash="h2")
    assert rate.pending([first, explained_again], ratings) == [explained_again]
    with pytest.raises(ValueError):
        rate.save_rating(tmp_path, first, "great")


def test_only_the_models_explanations_are_rated(tmp_path):
    by_code = explanation("quiet", verdict="unknown", source="code")
    assert rate.pending([by_code, explanation("e1")], {}) == [explanation("e1")]


def test_summary_splits_ratings_by_the_agents_verdict(tmp_path):
    explanations = [explanation("a"), explanation("b"), explanation("c"), explanation("d", verdict="possible"),
                    explanation("e", verdict="unknown"), explanation("f")]
    for episode_id, rating in (("a", "correct"), ("b", "correct"), ("c", "wrong"), ("d", "partly"), ("e", "cannot_tell")):
        rate.save_rating(tmp_path, next(e for e in explanations if e["episode_id"] == episode_id), rating)
    summary = rate.summarise(explanations, rate.load_ratings(tmp_path))
    assert (summary["rated"], summary["to_rate"]) == (5, 1)
    assert summary["by_verdict"]["likely"] == {"correct": 2, "partly": 0, "wrong": 1, "cannot_tell": 0}
    assert summary["by_verdict"]["possible"]["partly"] == 1
    report = rate.format_report(summary)
    assert "trafna w 2 z 3 ocenionych (67%)" in report
    assert "Brak ocenionych" in rate.format_report(rate.summarise(explanations, {}))


def test_undo_removes_the_last_rated_explanation(tmp_path):
    first, second = explanation("e1"), explanation("e2")
    rate.save_rating(tmp_path, first, "correct")
    rate.save_rating(tmp_path, second, "wrong")
    rate.save_rating(tmp_path, second, "partly")  # rated twice: both rows go
    assert rate.undo_last_rating(tmp_path) == "e2"
    assert list(rate.load_ratings(tmp_path)) == [("e1", "h1")]
    assert rate.undo_last_rating(tmp_path) == "e1"
    assert rate.load_ratings(tmp_path) == {}
    assert rate.undo_last_rating(tmp_path) is None
