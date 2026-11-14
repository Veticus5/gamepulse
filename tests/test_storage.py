import re

from gamepulse.storage import append_jsonl, read_jsonl, utc_now_iso


def test_append_creates_parents_and_roundtrips(tmp_path):
    path = tmp_path / "a" / "b" / "x.jsonl"
    records = [{"a": 1}, {"b": "zażółć"}]
    assert append_jsonl(path, records) == 2
    assert read_jsonl(path) == records


def test_append_twice_appends(tmp_path):
    path = tmp_path / "x.jsonl"
    append_jsonl(path, [{"a": 1}])
    append_jsonl(path, [{"a": 2}])
    assert path.read_text().count("\n") == 2
    assert read_jsonl(path) == [{"a": 1}, {"a": 2}]


def test_append_nothing_does_not_create_file(tmp_path):
    path = tmp_path / "x.jsonl"
    assert append_jsonl(path, []) == 0
    assert not path.exists()


def test_read_missing_file_returns_empty(tmp_path):
    assert read_jsonl(tmp_path / "nope.jsonl") == []


def test_read_skips_truncated_last_line(tmp_path):
    path = tmp_path / "x.jsonl"
    path.write_text('{"a":1}\n{"a":')
    assert read_jsonl(path) == [{"a": 1}]


def test_append_after_truncated_line_starts_new_line(tmp_path):
    path = tmp_path / "x.jsonl"
    path.write_text('{"a":1}\n{"a":')
    append_jsonl(path, [{"a": 2}])
    assert read_jsonl(path) == [{"a": 1}, {"a": 2}]


def test_utc_now_iso_format():
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", utc_now_iso())


def test_unicode_line_separators_do_not_split_records(tmp_path):
    path = tmp_path / "x.jsonl"
    records = [{"gid": "1", "contents": "a\u2028b\u2029c\x85d"}, {"gid": "2"}]
    append_jsonl(path, records)
    assert read_jsonl(path) == records


def test_lone_surrogate_is_stored_instead_of_raising(tmp_path):
    path = tmp_path / "x.jsonl"
    records = [{"gid": "1", "title": "cut emoji \ud83d"}, {"gid": "2", "title": "zażółć"}]
    assert append_jsonl(path, records) == 2
    assert read_jsonl(path) == records
    path.read_bytes().decode("utf-8")  # the file stays valid UTF-8
