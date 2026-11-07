"""Exercise release-time demo refreshes against an isolated Git remote."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/refresh-demo-pr.sh"
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


def commit_file(work, path, content):
    (work / path).write_text(content)
    git(work, "add", path)
    git(work, "commit", "-q", "-m", f"Update {path}")
    return git(work, "rev-parse", "HEAD")


@pytest.fixture
def demo(tmp_path):
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    git(tmp_path, "init", "-q", "--bare", str(origin))
    git(tmp_path, "init", "-q", "-b", "main", str(work))
    git(work, "remote", "add", "origin", str(origin))
    commit_file(work, "slide.md", "Original slide\n")
    git(work, "checkout", "-q", "-b", "example-demo-pr")
    sample = commit_file(work, "slide.md", "Sample slide edit\n")
    git(work, "checkout", "-q", "main")
    git(work, "push", "-q", "origin", "main", "example-demo-pr")
    return origin, work, sample


def refresh(work):
    head = git(work, "rev-parse", "HEAD")
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=work,
        capture_output=True,
        text=True,
        env={**os.environ, **GIT_ENV, "DEMO_BRANCH": "example-demo-pr"},
    )
    assert git(work, "rev-parse", "HEAD") == head
    assert git(work, "status", "--porcelain") == ""
    assert git(work, "worktree", "list", "--porcelain").count("worktree ") == 1
    return result


def test_merges_new_main_and_preserves_sample_edit(demo):
    origin, work, sample = demo
    main = commit_file(work, "release.txt", "Next release\n")
    git(work, "push", "-q", "origin", "main")

    result = refresh(work)

    assert result.returncode == 0, result.stderr
    assert git(origin, "show", "example-demo-pr:release.txt") == "Next release"
    assert git(origin, "show", "example-demo-pr:slide.md") == "Sample slide edit"
    assert git(origin, "rev-parse", "example-demo-pr^1") == sample
    assert git(origin, "rev-parse", "example-demo-pr^2") == main


def test_already_current_branch_still_pushes_a_refresh_commit(demo):
    origin, work, sample = demo
    assert git(origin, "rev-parse", "example-demo-pr") == sample

    for _ in range(2):
        before = git(origin, "rev-parse", "example-demo-pr")
        result = refresh(work)
        assert result.returncode == 0, result.stderr
        after = git(origin, "rev-parse", "example-demo-pr")
        assert after != before
        assert git(origin, "rev-parse", "example-demo-pr^") == before
        assert git(origin, "rev-parse", "example-demo-pr^{tree}") == git(
            origin, "rev-parse", f"{before}^{{tree}}"
        )


def test_conflict_does_not_push_or_change_callers_checkout(demo):
    origin, work, sample = demo
    commit_file(work, "slide.md", "Conflicting main edit\n")
    git(work, "push", "-q", "origin", "main")

    result = refresh(work)

    assert result.returncode == 1
    assert "conflicts; resolve it by hand" in result.stderr
    assert git(origin, "rev-parse", "example-demo-pr") == sample
