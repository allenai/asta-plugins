"""Exercise release failure reporting without GitHub writes."""

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPORT = yaml.safe_load((ROOT / ".github/workflows/example-workspace.yml").read_text())[
    "jobs"
]["report"]["steps"][0]["run"]
TITLE = "Example workspace failed to build for v0.109.0"


def reporter(tmp_path, issues=(), *, lookup_fails=False):
    state = tmp_path / "issues.json"
    state.write_text(json.dumps(list(issues)))
    log = tmp_path / "calls.jsonl"
    gh = tmp_path / "gh"
    gh.write_text(
        f"#!{sys.executable}\n"
        + """import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ["TEST_LOG"]).open("a") as output:
    output.write(json.dumps(args) + "\\n")
state = Path(os.environ["TEST_ISSUES"])
issues = json.loads(state.read_text())
if args[:2] == ["issue", "list"]:
    if os.environ["LOOKUP_FAILS"] == "1":
        sys.exit(22)
    assert args[args.index("--state") + 1] == "all"
    print(json.dumps(issues))
elif args[:2] == ["issue", "create"]:
    issues.append({"number": 42, "title": args[args.index("--title") + 1], "state": "OPEN"})
    state.write_text(json.dumps(issues))
elif args[:2] == ["issue", "reopen"]:
    next(issue for issue in issues if str(issue["number"]) == args[2])["state"] = "OPEN"
    state.write_text(json.dumps(issues))
elif args[:2] != ["issue", "comment"]:
    raise AssertionError(args)
"""
    )
    gh.chmod(0o755)
    env = {
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_REPOSITORY": "allenai/asta-plugins",
        "REF": "v0.109.0",
        "RUN": "https://github.com/allenai/asta-plugins/actions/runs/123",
        "TEST_LOG": str(log),
        "TEST_ISSUES": str(state),
        "LOOKUP_FAILS": "1" if lookup_fails else "0",
    }

    def run(attempt):
        env["RUN"] = f"https://github.com/allenai/asta-plugins/actions/runs/{attempt}"
        return subprocess.run(
            ["bash", "-c", REPORT],
            cwd=tmp_path,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
        )

    def calls():
        return [json.loads(line) for line in log.read_text().splitlines()]

    return run, calls


def test_failed_rerun_updates_the_existing_release_issue(tmp_path):
    run, calls = reporter(tmp_path)
    assert run(123).returncode == 0
    assert run(124).returncode == 0
    writes = [call for call in calls() if call[1] != "list"]
    assert [call[1] for call in writes] == ["create", "comment"]
    assert writes[1][2] == "42"
    assert writes[1][-1].endswith("/actions/runs/124")


def test_recurring_failure_reopens_the_release_issue(tmp_path):
    run, calls = reporter(tmp_path, [{"number": 7, "title": TITLE, "state": "CLOSED"}])
    assert run(125).returncode == 0
    writes = [call for call in calls() if call[1] != "list"]
    assert [call[1:3] for call in writes] == [["reopen", "7"], ["comment", "7"]]


def test_similar_issue_title_does_not_capture_another_release(tmp_path):
    run, calls = reporter(
        tmp_path, [{"number": 7, "title": TITLE + "-rc.1", "state": "OPEN"}]
    )
    assert run(126).returncode == 0
    assert [call[1] for call in calls()] == ["list", "create"]


def test_failed_lookup_does_not_create_a_duplicate_issue(tmp_path):
    run, calls = reporter(tmp_path, lookup_fails=True)
    assert run(127).returncode != 0
    assert [call[1] for call in calls()] == ["list"]
