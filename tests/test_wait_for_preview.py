import json
import os
import subprocess
from pathlib import Path

SCRIPT = Path(
    "plugins/asta-tools/skills/workspace/assets/wait-for-preview.sh"
).resolve()


def _project(tmp_path: Path, scenario: dict) -> tuple[Path, dict[str, str], Path]:
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "topic", project], check=True)
    (project / "content").write_text("test")
    subprocess.run(["git", "-C", project, "add", "content"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            project,
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-q",
            "-m",
            "test",
        ],
        check=True,
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state = tmp_path / "gh-state.json"
    config = tmp_path / "scenario.json"
    log = tmp_path / "gh.log"
    config.write_text(json.dumps(scenario))
    (fake_bin / "gh").write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

config = json.loads(Path(os.environ["FAKE_GH_SCENARIO"]).read_text())
state_path = Path(os.environ["FAKE_GH_STATE"])
state = json.loads(state_path.read_text()) if state_path.exists() else {}
args = sys.argv[1:]
with Path(os.environ["FAKE_GH_LOG"]).open("a") as log:
    log.write(json.dumps(args) + "\\n")

def next_value(key, default=""):
    index = state.get(key, 0)
    values = config.get(key, [default])
    value = values[min(index, len(values) - 1)]
    state[key] = index + 1
    state_path.write_text(json.dumps(state))
    return value

if args[:2] == ["run", "list"]:
    count = state.get("run_lists", 0)
    state["run_lists"] = count + 1
    state_path.write_text(json.dumps(state))
    if count:
        value = next_value("workflow_runs")
        if value == "ERROR":
            print('{"message":"temporary failure"}')
            sys.exit(1)
        print(value)
    else:
        print(config.get("baseline_run", "0"))
elif args[:2] == ["run", "watch"]:
    sys.exit(config.get("watch_exit", 0))
elif args and args[0] == "api" and "/commits/" in args[1]:
    print(next_value("pages_tips"))
elif args and args[0] == "api" and "/compare/" in args[1]:
    if config.get("compare_error"):
        sys.exit(1)
    print(config.get("comparison", "ahead 1 1 published"))
elif args and args[0] == "api" and "/pages/builds" in args[1]:
    print(next_value("builds", "1"))
else:
    raise SystemExit(f"unexpected gh command: {args}")
"""
    )
    (fake_bin / "gh").chmod(0o755)
    (fake_bin / "sleep").write_text("#!/bin/sh\nexit 0\n")
    (fake_bin / "sleep").chmod(0o755)

    env = {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "REPO": "owner/repo",
        "WORKFLOW_TIMEOUT": "10",
        "PAGES_TIMEOUT": "10",
        "POLL": "1",
        "FAKE_GH_SCENARIO": str(config),
        "FAKE_GH_STATE": str(state),
        "FAKE_GH_LOG": str(log),
    }
    return project, env, log


def _run(
    project: Path, env: dict[str, str], action: str
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sh", SCRIPT, action],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
    )


def test_wait_tracks_the_new_run_and_its_deployment_commit(tmp_path: Path) -> None:
    project, env, log = _project(
        tmp_path,
        {
            "pages_tips": ["before", "after"],
            "baseline_run": "100",
            "workflow_runs": ["ERROR", "101"],
            "comparison": "ahead 1 1 published",
            "builds": ["1"],
        },
    )

    assert _run(project, env, "baseline").returncode == 0
    result = _run(project, env, "wait")

    assert result.returncode == 0, result.stderr
    assert "Pages published published" in result.stdout
    assert not (project / ".git/preview-run-before").exists()
    commands = log.read_text()
    assert ".databaseId>100" in commands
    assert "(run 101)" in commands
    assert 'commit==\\"published\\"' in commands


def test_wait_ignores_concurrent_pages_commits_when_render_is_unchanged(
    tmp_path: Path,
) -> None:
    project, env, _ = _project(
        tmp_path,
        {
            "pages_tips": ["before", "someone-elses-tip"],
            "baseline_run": "100",
            "workflow_runs": ["101"],
            "comparison": "ahead 1 1",
        },
    )

    assert _run(project, env, "baseline").returncode == 0
    result = _run(project, env, "wait")

    assert result.returncode == 0, result.stderr
    assert "unrelated Pages updates were ignored" in result.stdout
    assert not (project / ".git/preview-run-before").exists()


def test_wait_preserves_baseline_when_remote_correlation_fails(tmp_path: Path) -> None:
    project, env, _ = _project(
        tmp_path,
        {
            "pages_tips": ["before", "after"],
            "baseline_run": "100",
            "workflow_runs": ["101"],
            "compare_error": True,
        },
    )

    assert _run(project, env, "baseline").returncode == 0
    result = _run(project, env, "wait")

    assert result.returncode == 1
    assert "Could not correlate" in result.stderr
    assert (project / ".git/preview-run-before").read_text() == "before\n100\n"


def test_wait_rejects_invalid_timing_values(tmp_path: Path) -> None:
    project, env, _ = _project(tmp_path, {})
    env["PAGES_TIMEOUT"] = "0"

    result = _run(project, env, "baseline")

    assert result.returncode == 2
    assert "PAGES_TIMEOUT must be a positive integer" in result.stderr


def test_wait_omits_branch_filter_from_detached_head(tmp_path: Path) -> None:
    project, env, log = _project(
        tmp_path,
        {
            "pages_tips": ["same", "same"],
            "baseline_run": "100",
            "workflow_runs": ["101"],
        },
    )
    assert _run(project, env, "baseline").returncode == 0
    subprocess.run(["git", "checkout", "--detach", "-q"], cwd=project, check=True)

    result = _run(project, env, "wait")

    assert result.returncode == 0, result.stderr
    run_lists = [
        json.loads(line)
        for line in log.read_text().splitlines()
        if json.loads(line)[:2] == ["run", "list"]
    ]
    assert "--branch" not in run_lists[-1]
