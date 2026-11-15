import subprocess

import pytest

from gamepulse import sync_remote


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                   check=True, capture_output=True)


@pytest.fixture
def repos(tmp_path):
    """A bare "GitHub", a writer standing in for the workflow, and the local clone."""
    hub = tmp_path / "hub.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(hub)], check=True, capture_output=True)
    writer = tmp_path / "writer"
    subprocess.run(["git", "clone", str(hub), str(writer)], check=True, capture_output=True)
    git(writer, "switch", "--orphan", "data")
    local = tmp_path / "local"
    subprocess.run(["git", "clone", str(hub), str(local)], check=True, capture_output=True)

    def publish(path, text):
        target = writer / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a") as handle:
            handle.write(text)
        git(writer, "add", "-A")
        git(writer, "commit", "-m", "data")
        git(writer, "push", "origin", "data")

    return local, publish


def test_pull_copies_measurements_under_a_prefix(repos, tmp_path):
    local, publish = repos
    publish("raw/ccu/2026-11-15.jsonl", '{"appid": 730}\n')
    publish("raw/fivem/2026-11-15.jsonl", '{"counts": [1]}\n')
    publish("raw/other/x.jsonl", "ignored\n")
    publish("README.md", "ignored\n")
    data = tmp_path / "data"
    (data / "raw" / "ccu").mkdir(parents=True)
    (data / "raw" / "ccu" / "2026-11-15.jsonl").write_text("local\n")  # the local collector's own file
    assert sync_remote.pull(local, data) == 2
    assert (data / "raw" / "ccu" / "gh-2026-11-15.jsonl").read_text() == '{"appid": 730}\n'
    assert (data / "raw" / "fivem" / "gh-2026-11-15.jsonl").read_text() == '{"counts": [1]}\n'
    assert (data / "raw" / "ccu" / "2026-11-15.jsonl").read_text() == "local\n"
    assert not (data / "raw" / "other").exists()


def test_pull_updates_only_what_changed(repos, tmp_path):
    local, publish = repos
    publish("raw/ccu/2026-11-15.jsonl", "a\n")
    data = tmp_path / "data"
    sync_remote.pull(local, data)
    assert sync_remote.pull(local, data) == 0
    publish("raw/ccu/2026-11-15.jsonl", "b\n")
    publish("raw/ccu/2026-11-16.jsonl", "c\n")
    assert sync_remote.pull(local, data) == 2
    assert (data / "raw" / "ccu" / "gh-2026-11-15.jsonl").read_text() == "a\nb\n"


def test_pull_reports_a_missing_branch_or_remote(repos, tmp_path):
    local, _ = repos
    with pytest.raises(sync_remote.RemoteError):
        sync_remote.pull(local, tmp_path / "data")  # nothing was published yet
    with pytest.raises(sync_remote.RemoteError):
        sync_remote.pull(tmp_path, tmp_path / "data")  # not a repository
