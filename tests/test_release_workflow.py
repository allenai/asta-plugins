"""Exercise the release workflow's tag and Docker recovery paths."""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TAG = "v1.2.3"
TAG_REF = f"refs/tags/{TAG}"
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def git(cwd, *args):
    return subprocess.check_output(
        ["git", *args], cwd=cwd, env=GIT_ENV, text=True
    ).strip()


class Release:
    def __init__(self, path):
        self.path = path
        self.origin = path / "origin.git"
        self.work = path / "work"
        git(path, "init", "-q", "--bare", str(self.origin))
        git(path, "init", "-q", "-b", "main", str(self.work))
        git(self.work, "remote", "add", "origin", self.origin.as_uri())
        git(self.work, "commit", "--allow-empty", "-qm", "Version bump")
        self.checked = git(self.work, "rev-parse", "HEAD")
        git(self.work, "commit", "--allow-empty", "-qm", "Another push to main")
        self.later = git(self.work, "rev-parse", "HEAD")
        git(self.work, "push", "-q", "origin", "main")
        gh = path / "gh"
        gh.write_text(
            """#!/usr/bin/env python3
import os
import sys

with open(os.environ["GH_LOG"], "a") as log:
    print(" ".join(sys.argv[1:]), file=log)

match sys.argv[1:3]:
    case ["run", "list"]:
        print(os.environ["DOCKER_RUNS"])
    case ["api", "--method"]:
        if sys.argv[3] == "POST":
            if os.environ.get("DISPATCH_FAILURE"):
                sys.exit(1)
            print(os.environ["DISPATCH_RESPONSE"])
    case ["api", "--paginate"]:
        print(os.environ["PR_COMMENTS"])
    case ["api", _]:
        print("7")
    case ["pr", "comment"]:
        pass
    case ["run", "watch"]:
        sys.exit(int(os.environ["WATCH_EXIT"]))
    case _:
        sys.exit(2)
"""
        )
        gh.chmod(0o755)

    def env(self, **overrides):
        return {
            **GIT_ENV,
            "GITHUB_OUTPUT": str(self.path / "output"),
            "GITHUB_REPOSITORY": "test/repo",
            "GITHUB_SERVER_URL": "https://github.com",
            "GH_LOG": str(self.path / "gh.log"),
            "PATH": f"{self.path}:{os.environ['PATH']}",
            "DOCKER_RUNS": "[]",
            "DISPATCH_RESPONSE": json.dumps(
                {
                    "workflow_run_id": 42,
                    "run_url": "https://api.github.com/repos/test/repo/actions/runs/42",
                    "html_url": "https://github.com/test/repo/actions/runs/42",
                }
            ),
            "WATCH_EXIT": "0",
            **overrides,
        }

    def run(self, operation, *args, **env):
        output = self.path / "output"
        output.write_text("")
        result = subprocess.run(
            [str(ROOT / "scripts/release-tag.sh"), operation, TAG, *args],
            env=self.env(**env),
            cwd=self.work,
            capture_output=True,
            text=True,
        )
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        return result, outputs

    def manual_tag(self, commit, annotated):
        options = ["-m", "Manual release"] if annotated else []
        git(self.work, "tag", *options, TAG, commit)
        git(self.work, "push", "-q", "origin", TAG_REF)


@pytest.fixture
def release(tmp_path):
    return Release(tmp_path)


def test_later_main_push_recovers_the_original_tag_commit(release):
    result, outputs = release.run("plan")
    assert result.returncode == 0, result.stderr
    assert outputs == {"create_tag": "true"}

    result, _ = release.run("push", release.checked)
    assert result.returncode == 0, result.stderr
    assert git(release.origin, "rev-parse", f"{TAG_REF}^{{commit}}") == release.checked

    result, outputs = release.run("plan")
    assert result.returncode == 0, result.stderr
    assert outputs == {"tag_sha": release.checked}


@pytest.mark.parametrize("annotated", [False, True])
def test_manual_tag_at_checked_commit_is_left_alone(release, annotated):
    release.manual_tag(release.checked, annotated)
    before = git(release.origin, "rev-parse", TAG_REF)
    result, outputs = release.run("plan")
    assert result.returncode == 0, result.stderr
    assert outputs == {}
    result, _ = release.run("push", release.checked)
    assert result.returncode == 0, result.stderr
    assert git(release.origin, "rev-parse", TAG_REF) == before


def test_conflicting_tag_is_neither_moved_nor_dispatched(release):
    release.manual_tag(release.later, annotated=True)
    result, _ = release.run("push", release.checked)
    assert result.returncode != 0
    assert git(release.origin, "rev-parse", f"{TAG_REF}^{{commit}}") == release.later

    result, outputs = release.run("promote", release.checked)
    assert result.returncode != 0
    assert outputs == {}
    assert not (release.path / "gh.log").exists()


@pytest.mark.parametrize(
    ("event", "status", "conclusion", "retry", "watched"),
    [
        ("workflow_dispatch", "completed", "success", "false", None),
        ("workflow_dispatch", "in_progress", None, "false", "24"),
        ("workflow_dispatch", "completed", "failure", "false", None),
        ("workflow_dispatch", "completed", "failure", "true", "42"),
        ("push", "completed", "success", "false", None),
        ("pull_request", "completed", "success", "false", "42"),
    ],
)
def test_promotion_reuses_active_and_successful_runs(
    release, event, status, conclusion, retry, watched
):
    release.manual_tag(release.checked, annotated=True)
    runs = [
        {
            "databaseId": 24,
            "event": event,
            "status": status,
            "conclusion": conclusion,
        }
    ]
    result, outputs = release.run(
        "promote",
        release.checked,
        DOCKER_RUNS=json.dumps(runs),
        RETRY_FAILED_DOCKER=retry,
    )
    assert result.returncode == 0, result.stderr
    commands = (release.path / "gh.log").read_text().splitlines()
    assert f"--branch {TAG} --commit {release.checked}" in commands[0]
    if watched == "42":
        assert f"ref={TAG_REF}" in commands[1]
        assert f"inputs[expected-sha]={release.checked}" in commands[1]
        assert "X-GitHub-Api-Version: 2026-03-10" in commands[1]
    else:
        assert not any(command.startswith("api ") for command in commands)
    assert outputs["tag_verified"] == "true"
    if watched:
        assert commands[-1].startswith(f"run watch {watched} ")
        assert outputs["run_url"].endswith(f"/{watched}")
    else:
        assert len(commands) == 1
        assert "run_url" not in outputs


def test_dispatch_and_docker_failures_preserve_the_tag_for_retry(release):
    result, _ = release.run("push", release.checked)
    assert result.returncode == 0, result.stderr

    result, outputs = release.run("promote", release.checked, DISPATCH_FAILURE="1")
    assert result.returncode != 0
    assert outputs == {"tag_verified": "true"}

    result, outputs = release.run("promote", release.checked, WATCH_EXIT="1")
    assert result.returncode != 0
    assert outputs["run_url"].endswith("/42")

    result, outputs = release.run("plan")
    assert result.returncode == 0, result.stderr
    assert outputs == {"tag_sha": release.checked}


@pytest.mark.parametrize("body", ["", "{}", '{"workflow_run_id":"42"}'])
def test_dispatch_requires_a_numeric_run_id(release, body):
    release.manual_tag(release.checked, annotated=True)
    result, outputs = release.run("promote", release.checked, DISPATCH_RESPONSE=body)
    assert result.returncode != 0
    assert "Docker dispatch did not return a run ID" in result.stdout
    assert outputs == {"tag_verified": "true"}
    assert "run watch" not in (release.path / "gh.log").read_text()


@pytest.mark.parametrize(
    ("event", "ref", "expected_sha", "valid"),
    [
        ("workflow_dispatch", TAG_REF, "actual-sha", True),
        ("workflow_dispatch", TAG_REF, "", False),
        ("workflow_dispatch", TAG_REF, "other-sha", False),
        ("workflow_dispatch", f"refs/heads/{TAG}", "actual-sha", False),
        ("push", f"{TAG_REF}-rc.1", "", True),
    ],
)
def test_docker_dispatch_rejects_a_branch_or_unverified_commit(
    event, ref, expected_sha, valid
):
    workflow = yaml.safe_load((ROOT / ".github/workflows/docker.yml").read_text())
    promote = workflow["jobs"]["promote"]
    assert "github.event_name == 'workflow_dispatch' ||" in promote["if"]
    result = subprocess.run(
        ["bash", "-e", "-c", promote["steps"][0]["run"]],
        env={
            "GITHUB_EVENT_NAME": event,
            "GITHUB_REF": ref,
            "GITHUB_SHA": "actual-sha",
            "EXPECTED_SHA": expected_sha,
        },
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) == valid, result.stdout + result.stderr


@pytest.mark.parametrize("existing", [False, True])
def test_failure_report_updates_only_the_workflows_own_comment(release, existing):
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    report = workflow["jobs"]["report-failure"]["steps"][0]["run"]
    marker = f"<!-- asta-release-failure: {TAG} -->\n"
    comments = [{"id": 8, "user": {"login": "someone"}, "body": marker}]
    if existing:
        comments.append(
            {"id": 9, "user": {"login": "github-actions[bot]"}, "body": marker}
        )
    result = subprocess.run(
        ["bash", "-c", report],
        env=release.env(
            TAG=TAG,
            RELEASE_SHA=release.checked,
            CHECKS="failure",
            IMAGE="success",
            PROMOTION="skipped",
            RUN_URL="https://github.com/test/repo/actions/runs/10",
            PR_COMMENTS=json.dumps([comments]),
        ),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    commands = (release.path / "gh.log").read_text()
    if existing:
        assert "api --method PATCH repos/test/repo/issues/comments/9" in commands
        assert "pr comment" not in commands
    else:
        assert "pr comment 7" in commands
        assert "PATCH" not in commands


def test_release_calls_keep_the_x86_browser_gate_on_push():
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/example-preview.yml").read_text()
    )
    condition = workflow["jobs"]["check-preview"]["if"]
    assert "(github.event_name != 'push' || inputs.release-check)" in condition


def test_release_checks_disable_site_publication():
    release_checks = yaml.safe_load(
        (ROOT / ".github/workflows/workspace-release-checks.yml").read_text()
    )
    site = yaml.safe_load((ROOT / ".github/workflows/example-preview.yml").read_text())
    assert release_checks["jobs"]["site"]["with"]["release-check"] is True
    assert site["jobs"]["docs"]["with"]["publish"] == "${{ !inputs.release-check }}"
    assert site["jobs"]["docs-arm"]["with"]["publish"] is False
