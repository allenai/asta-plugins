"""Exercise the release step that fast-forwards the latest branch."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/docker.yml").read_text())
JOB = WORKFLOW["jobs"]["latest-branch"]
STEP = next(
    step
    for step in JOB["steps"]
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


def test_write_access_is_confined_to_branch_publication_jobs():
    jobs = WORKFLOW["jobs"]
    writers = {
        name
        for name, job in jobs.items()
        if job["permissions"].get("contents") == "write"
    }
    assert writers == {"latest-branch", "demo-pr"}
    example = jobs["example-workspace"]
    assert example["uses"] == "./.github/workflows/example-workspace.yml"
    assert example["needs"] == "latest"
    assert example["if"] == (
        "startsWith(github.ref, 'refs/tags/v') && !contains(github.ref_name, '-rc.')"
    )
    called = yaml.safe_load(
        (ROOT / ".github/workflows/example-workspace.yml").read_text()
    )
    assert [
        name
        for name, job in called["jobs"].items()
        if job.get("permissions", called.get("permissions", {})).get("contents")
        == "write"
    ] == []
    assert JOB["permissions"] == {"contents": "write"}
    assert [step.get("uses", "").split("@")[0] for step in JOB["steps"]] == [
        "actions/checkout",
        "",
    ]
    assert JOB["needs"] == "latest"
    assert STEP["env"]["NEWEST"] == "${{ needs.latest.outputs.version }}"
    assert jobs["latest"]["outputs"]["version"] == "${{ steps.newest.outputs.version }}"


@pytest.mark.parametrize(
    "head_response", ["current", "stale-then-current", "stale", "api-error"]
)
def test_demo_release_rebuilds_the_patch_and_dispatches_its_preview(
    release, tmp_path, head_response
):
    origin, work, _, _ = release
    # Populate the tagged release with the real patch's input files.
    patch = ROOT / "examples/workspace-demo.patch"
    for line in patch.read_text().splitlines():
        if line.startswith("--- a/"):
            relative = line.removeprefix("--- a/")
            destination = work / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
    (work / "examples/workspace-demo.patch").write_bytes(patch.read_bytes())
    git(work, "add", "examples")
    git(work, "commit", "-qm", "release with sample patch")
    release_sha = git(work, "rev-parse", "HEAD")
    git(work, "tag", "v3.0.0")
    git(work, "push", "-q", "origin", "main", "--tags")
    fake = tmp_path / "gh"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import os, subprocess, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "if args[0] == 'api':\n"
        "    assert args[1:] == ['repos/owner/repo/pulls/281', '--jq', '.head.sha']\n"
        "    log = Path(os.environ['POLL_LOG'])\n"
        "    count = len(log.read_text().splitlines()) if log.exists() else 0\n"
        "    with log.open('a') as out: out.write('poll\\n')\n"
        "    mode = os.environ['HEAD_RESPONSE']\n"
        "    if mode == 'api-error': sys.exit(1)\n"
        "    if mode == 'stale' or (mode == 'stale-then-current' and count < 2):\n"
        "        print('a' * 40)\n"
        "    else:\n"
        "        print(subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip())\n"
        "else:\n"
        "    assert args[:2] == ['workflow', 'run']\n"
        "    with open(os.environ['DISPATCH_LOG'], 'a') as out: out.write(' '.join(args) + '\\n')\n"
    )
    fake.chmod(0o755)
    sleep = tmp_path / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n")
    sleep.chmod(0o755)
    job = WORKFLOW["jobs"]["demo-pr"]
    assert job["permissions"] == {
        "contents": "write",
        "actions": "write",
        "pull-requests": "read",
    }
    script = job["steps"][-1]["run"]
    for _ in range(2):
        polls = tmp_path / "polls"
        polls.unlink(missing_ok=True)
        result = subprocess.run(
            ["bash", "-c", script],
            cwd=work,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                **GIT_ENV,
                "NEWEST": "v3.0.0",
                "PATH": f"{tmp_path}:{os.environ['PATH']}",
                "GITHUB_REPOSITORY": "owner/repo",
                "DISPATCH_LOG": str(tmp_path / "dispatches"),
                "POLL_LOG": str(polls),
                "HEAD_RESPONSE": head_response,
            },
        )
        if head_response in ("stale", "api-error"):
            assert result.returncode != 0
            assert not (tmp_path / "dispatches").exists()
            if head_response == "stale":
                assert "preview not dispatched" in result.stdout
                assert len(polls.read_text().splitlines()) == 30
            return
        assert result.returncode == 0, result.stderr
        assert len(polls.read_text().splitlines()) == (
            3 if head_response == "stale-then-current" else 1
        )
        head = git(origin, "rev-parse", "refs/heads/example-demo-pr")
        assert git(work, "rev-parse", f"{head}^") == release_sha
        assert re.sub(
            r"^index .+\n", "", git(work, "diff", release_sha, head), flags=re.M
        ) == re.sub(r"^index .+\n", "", patch.read_text().strip(), flags=re.M)
    assert (tmp_path / "dispatches").read_text().splitlines() == [
        "workflow run example-preview.yml --repo owner/repo --ref example-demo-pr -f preview-pr=281"
    ] * 2
