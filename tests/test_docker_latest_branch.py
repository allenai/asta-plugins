"""Exercise the release step that fast-forwards the latest branch."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/docker.yml").read_text())
STEP = next(
    step
    for step in WORKFLOW["jobs"]["latest"]["steps"]
    if step.get("name") == "Fast-forward the latest branch to that release"
)
GIT_ENV = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def git(cwd, *args):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **GIT_ENV},
    ).stdout.strip()


def commit(cwd, message):
    git(cwd, "commit", "--allow-empty", "-q", "-m", message)
    return git(cwd, "rev-parse", "HEAD")


@pytest.fixture
def release(tmp_path):
    """An origin with v1 on latest and v2 tagged ahead of it, plus a checkout."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    git(tmp_path, "init", "-q", "--bare", str(origin))
    git(tmp_path, "init", "-q", "-b", "main", str(work))
    git(work, "remote", "add", "origin", str(origin))
    v1 = commit(work, "v1")
    git(work, "tag", "v1.0.0")
    v2 = commit(work, "v2")
    git(work, "tag", "v2.0.0")
    git(work, "push", "-q", "origin", "main", "--tags", f"{v1}:refs/heads/latest")
    return origin, work, v1, v2


def run_step(work, newest):
    return subprocess.run(
        ["bash", "-c", STEP["run"]],
        cwd=work,
        capture_output=True,
        text=True,
        env={**os.environ, **GIT_ENV, "NEWEST": newest},
    )


def latest(origin):
    return git(origin, "rev-parse", "refs/heads/latest")


def test_fast_forwards_to_the_newest_release(release):
    origin, work, _, v2 = release
    result = run_step(work, "v2.0.0")
    assert result.returncode == 0, result.stderr
    assert latest(origin) == v2


def test_never_moves_backwards(release):
    origin, work, _, v2 = release
    git(work, "push", "-q", "origin", f"{v2}:refs/heads/latest")
    result = run_step(work, "v1.0.0")
    assert result.returncode == 0, result.stderr
    assert "already includes" in result.stdout
    assert latest(origin) == v2


def test_refuses_a_diverged_branch(release):
    origin, work, v1, _ = release
    git(work, "checkout", "-q", "--detach", v1)
    side = commit(work, "side")
    git(work, "push", "-q", "origin", f"{side}:refs/heads/latest")
    result = run_step(work, "v2.0.0")
    assert result.returncode == 1
    assert latest(origin) == side
