"""Exercise release-time demo refreshes against an isolated Git remote."""

import os
import shlex
import shutil
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


def refresh(work, *args, branch="example-demo-pr", env=None):
    head = git(work, "rev-parse", "HEAD")
    result = subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=work,
        capture_output=True,
        text=True,
        env={**os.environ, **GIT_ENV, "DEMO_BRANCH": branch, **(env or {})},
    )
    assert git(work, "rev-parse", "HEAD") == head
    assert git(work, "status", "--porcelain") == ""
    assert git(work, "worktree", "list", "--porcelain").count("worktree ") == 1
    return result


def test_single_branch_clone_fetches_the_demo_branch(demo, tmp_path):
    origin, _, _ = demo
    work = tmp_path / "single-branch"
    git(
        tmp_path, "clone", "-q", "--single-branch", "-b", "main", str(origin), str(work)
    )

    result = refresh(work)

    assert result.returncode == 0, result.stderr
    assert git(origin, "show", "example-demo-pr:slide.md") == "Sample slide edit"


def test_narrow_fetch_refspec_cannot_leave_main_stale(demo):
    origin, work, _ = demo
    git(
        work,
        "config",
        "remote.origin.fetch",
        "+refs/heads/example-demo-pr:refs/remotes/origin/example-demo-pr",
    )
    main = commit_file(work, "release.txt", "New main\n")
    git(work, "push", "-q", "origin", "main")

    result = refresh(work)

    assert result.returncode == 0, result.stderr
    assert git(origin, "rev-parse", "example-demo-pr^2") == main
    assert git(origin, "show", "example-demo-pr:release.txt") == "New main"


def test_release_ref_does_not_merge_newer_main(demo):
    origin, work, _ = demo
    release = commit_file(work, "release.txt", "Tagged release\n")
    git(work, "tag", "v1.0.0", release)
    commit_file(work, "unreleased.txt", "Not in the release\n")
    git(work, "push", "-q", "origin", "main")

    result = refresh(work, release)

    assert result.returncode == 0, result.stderr
    assert git(origin, "rev-parse", "example-demo-pr^2") == release
    assert git(origin, "show", "example-demo-pr:release.txt") == "Tagged release"
    assert (
        "unreleased.txt"
        not in git(origin, "ls-tree", "--name-only", "example-demo-pr").splitlines()
    )


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
    assert "failed (possibly conflicts); resolve it by hand" in result.stderr
    assert git(origin, "rev-parse", "example-demo-pr") == sample


def test_missing_demo_branch_leaves_no_temporary_directory(demo, tmp_path):
    origin, work, sample = demo
    temp = tmp_path / "temps"
    temp.mkdir()

    result = refresh(work, branch="missing-demo", env={"TMPDIR": str(temp)})

    assert result.returncode != 0
    assert list(temp.iterdir()) == []
    assert git(origin, "rev-parse", "example-demo-pr") == sample


def test_failed_worktree_add_cleans_up_empty_directory(demo, tmp_path):
    origin, work, sample = demo
    temp = tmp_path / "temps"
    temp.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "git"
    shim.write_text(
        '#!/bin/sh\nif [ "$1" = worktree ] && [ "$2" = add ]; then exit 1; fi\n'
        f'exec {shlex.quote(shutil.which("git"))} "$@"\n'
    )
    shim.chmod(0o755)

    result = refresh(
        work,
        env={"TMPDIR": str(temp), "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"},
    )

    assert result.returncode != 0
    assert list(temp.iterdir()) == []
    assert git(origin, "rev-parse", "example-demo-pr") == sample


def test_concurrent_demo_update_rejects_push_without_overwriting_it(demo):
    origin, work, _ = demo
    git(work, "checkout", "-q", "example-demo-pr")
    concurrent = commit_file(work, "concurrent.txt", "Another contributor's edit\n")
    git(work, "checkout", "-q", "main")
    git(work, "push", "-q", "origin", f"{concurrent}:refs/heads/concurrent")
    hook = work / ".git/hooks/pre-push"
    hook.write_text(
        "#!/bin/sh\n"
        f"git --git-dir={shlex.quote(str(origin))} update-ref refs/heads/example-demo-pr {concurrent}\n"
    )
    hook.chmod(0o755)

    result = refresh(work)

    assert result.returncode != 0
    assert git(origin, "rev-parse", "example-demo-pr") == concurrent
    assert (
        git(origin, "show", "example-demo-pr:concurrent.txt")
        == "Another contributor's edit"
    )


def test_refresh_respects_commit_hooks(demo):
    origin, work, sample = demo
    hook = work / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\necho 'Commit hook refused refresh' >&2\nexit 1\n")
    hook.chmod(0o755)

    result = refresh(work)

    assert result.returncode != 0
    assert "Commit hook refused refresh" in result.stderr
    assert git(origin, "rev-parse", "example-demo-pr") == sample


def test_rejects_option_like_demo_branch_before_fetching(demo):
    origin, work, sample = demo

    result = refresh(work, branch="--invalid-branch")

    assert result.returncode != 0
    assert "not a valid branch name" in result.stderr
    assert git(origin, "rev-parse", "example-demo-pr") == sample
