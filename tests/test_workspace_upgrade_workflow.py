"""Execute the upgrade workflow's shell against a deterministic GitHub API."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.test_workspace_workflow import _condition_enabled

WORKFLOW = Path(".github/workflows/workspace-dependabot-upgrade.yml")
HEAD = "a" * 40
OPEN = {"state": "OPEN", "headRefOid": HEAD, "baseRefName": "trunk"}
PASS = [
    {"name": "docs / build", "bucket": "pass"},
    {"name": "docs / paper-gate", "bucket": "skipping"},
]


def _job():
    return yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)["jobs"][
        "merge-and-deploy"
    ]


def _step(step_id):
    return next(step for step in _job()["steps"] if step.get("id") == step_id)


def test_upgrade_stub_grants_the_called_workflows_check_read_permissions():
    stub = yaml.load(
        Path(
            "plugins/asta-tools/skills/workspace/assets/asta-plugins-upgrade.yml"
        ).read_text(),
        Loader=yaml.BaseLoader,
    )
    assert stub["permissions"] == _job()["permissions"]
    assert stub["permissions"]["checks"] == "read"
    assert stub["permissions"]["statuses"] == "read"


@pytest.mark.parametrize(
    "overrides,enabled",
    [
        ({}, True),
        ({"github.event_name": "push"}, False),
        ({"github.event.pull_request.user.login": "contributor"}, False),
        ({"github.event.pull_request.head.repo.full_name": "fork/site"}, False),
        ({"github.event.pull_request.base.ref": "topic"}, False),
        ({"github.event.repository.fork": True}, False),
    ],
)
def test_upgrade_is_limited_to_dependabot_in_the_default_branch_repo(
    overrides, enabled
):
    context = {
        "github.event_name": "pull_request",
        "github.repository": "owner/site",
        "github.event.pull_request.user.login": "dependabot[bot]",
        "github.event.pull_request.head.repo.full_name": "owner/site",
        "github.event.pull_request.base.ref": "trunk",
        "github.event.repository.default_branch": "trunk",
        "github.event.repository.fork": False,
        **overrides,
    }
    assert _condition_enabled(_job()["if"], context) == enabled
    metadata = _step("metadata")
    assert metadata["uses"] == (
        "dependabot/fetch-metadata@25dd0e34f4fe68f24cc83900b1fe3fe149efef98"
    )
    # Keep the action's verification of every Dependabot commit enabled.
    assert "skip-commit-verification" not in metadata.get("with", {})
    assert "skip-verification" not in metadata.get("with", {})
    # No code from the PR is executed with the write-enabled token.
    assert not any("checkout" in step.get("uses", "") for step in _job()["steps"])


@pytest.mark.parametrize(
    "names,update_type,eligible",
    [
        ("allenai/asta-plugins", "version-update:semver-patch", True),
        (
            "allenai/asta-plugins, allenai/asta-plugins",
            "version-update:semver-minor",
            True,
        ),
        ("allenai/asta-plugins", "version-update:semver-major", False),
        ("allenai/asta-plugins", "", False),
        ("allenai/asta-plugins", "unknown", False),
        ("", "version-update:semver-patch", False),
        ("other/asta-plugins", "version-update:semver-minor", False),
        (
            "allenai/asta-plugins, actions/checkout",
            "version-update:semver-patch",
            False,
        ),
    ],
)
def test_only_known_patch_and_minor_asta_upgrades_are_eligible(
    tmp_path, names, update_type, eligible
):
    output = tmp_path / "output"
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", _step("eligible")["run"]],
        env={
            **os.environ,
            "NAMES": names,
            "UPDATE_TYPE": update_type,
            "GITHUB_OUTPUT": str(output),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert output.read_text().strip() == f"eligible={str(eligible).lower()}"


def _run_upgrade(tmp_path, scenario, *, wait_minutes="1", docs_check="docs / build"):
    """Run the actual merge and dispatch scripts; replace only external effects."""
    scenario_file = tmp_path / "scenario.json"
    scenario_file.write_text(json.dumps(scenario))
    log = tmp_path / "commands.jsonl"
    log.touch()
    output = tmp_path / "output"
    output.touch()
    clock = tmp_path / "clock"
    clock.write_text("0")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "log = Path(os.environ['COMMAND_LOG'])\n"
        "previous = [json.loads(line) for line in log.read_text().splitlines()]\n"
        "with log.open('a') as stream: stream.write(json.dumps(args) + '\\n')\n"
        "scenario = json.loads(Path(os.environ['SCENARIO']).read_text())\n"
        "count = sum(command[:2] == args[:2] for command in previous)\n"
        "if args[:2] == ['pr', 'view']:\n"
        "    views = scenario.get('views', [json.loads(os.environ['OPEN_PR'])])\n"
        "    print(json.dumps(views[min(count, len(views) - 1)]))\n"
        "elif args[:2] == ['pr', 'checks']:\n"
        "    checks = scenario.get('checks', [[]])\n"
        "    print(json.dumps(checks[min(count, len(checks) - 1)]))\n"
        "    sys.exit(scenario.get('checks_exit', 0))\n"
        "elif args[:1] == ['api']:\n"
        "    print(scenario.get('merge_result', 'true'))\n"
        "    sys.exit(scenario.get('merge_exit', 0))\n"
        "elif args[:2] == ['workflow', 'run']:\n"
        "    sys.exit(int(count < scenario.get('dispatch_failures', 0)))\n"
        "else:\n"
        "    raise AssertionError(args)\n"
    )
    gh.chmod(0o755)
    for name, script in {
        "date": 'cat "$CLOCK"',
        "sleep": 'value=$(cat "$CLOCK"); echo $(( value + $1 )) > "$CLOCK"',
    }.items():
        path = bin_dir / name
        path.write_text(f"#!/bin/sh\n{script}\n")
        path.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SCENARIO": str(scenario_file),
        "COMMAND_LOG": str(log),
        "CLOCK": str(clock),
        "GITHUB_OUTPUT": str(output),
        "GITHUB_REPOSITORY": "owner/site",
        "PR_URL": "https://github.com/owner/site/pull/7",
        "PR_NUMBER": "7",
        "EXPECTED_HEAD": HEAD,
        "DEFAULT_BRANCH": "trunk",
        "DOCS_CHECK": docs_check,
        "DOCS_WORKFLOW": "site.yml",
        "WAIT_MINUTES": wait_minutes,
        "OPEN_PR": json.dumps(OPEN),
    }
    merge = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", _step("merged")["run"]],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    deploy = None
    if "merged=true" in output.read_text():
        step = _job()["steps"][-1]
        assert step["if"] == "steps.merged.outputs.merged == 'true'"
        deploy = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", step["run"]],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
    return merge, deploy, [json.loads(line) for line in log.read_text().splitlines()]


def test_passing_checks_merge_the_tested_head_then_dispatch_the_default_branch(
    tmp_path,
):
    merge, deploy, commands = _run_upgrade(
        tmp_path,
        {"checks": [[{"name": "docs / build", "bucket": "pending"}], PASS]},
    )
    assert merge.returncode == 0, merge.stderr
    assert deploy is not None and deploy.returncode == 0, deploy
    assert sum(command[:2] == ["pr", "checks"] for command in commands) == 2
    assert commands[-2:] == [
        [
            "api",
            "--method",
            "PUT",
            "repos/owner/site/pulls/7/merge",
            "-f",
            f"sha={HEAD}",
            "-f",
            "merge_method=squash",
            "--jq",
            ".merged",
        ],
        ["workflow", "run", "site.yml", "--repo", "owner/site", "--ref", "trunk"],
    ]


@pytest.mark.parametrize(
    "checks,checks_exit",
    [
        ([], 0),  # no required checks configured
        ([], 1),  # CLI/API failure
        ([{"name": "other", "bucket": "pass"}], 0),  # docs is not required
        ([{"name": "docs / build", "bucket": "pending"}], 0),
        ([{"name": "docs / build", "bucket": "fail"}], 0),
        ([{"name": "docs / build", "bucket": "cancel"}], 0),
        ([{"name": "docs / build", "bucket": "skipping"}], 0),
        (PASS + [{"name": "other", "bucket": "fail"}], 0),
        (PASS + [{"name": "other", "bucket": "pending"}], 0),
    ],
)
def test_missing_or_unsuccessful_required_checks_never_merge_or_queue(
    tmp_path, checks, checks_exit
):
    merge, deploy, commands = _run_upgrade(
        tmp_path, {"checks": [checks], "checks_exit": checks_exit}
    )
    assert merge.returncode != 0
    assert deploy is None
    assert all(command[:1] != ["api"] for command in commands)
    assert all(command[:2] != ["pr", "merge"] for command in commands)


@pytest.mark.parametrize(
    "view",
    [
        {**OPEN, "headRefOid": "b" * 40},
        {**OPEN, "baseRefName": "topic"},
        {**OPEN, "state": "CLOSED"},
    ],
)
def test_changed_or_closed_pr_is_left_alone(tmp_path, view):
    merge, deploy, commands = _run_upgrade(
        tmp_path, {"views": [view], "checks": [PASS]}
    )
    assert merge.returncode == 0
    assert deploy is None
    assert len(commands) == 1


@pytest.mark.parametrize("merge_exit,merge_result", [(1, ""), (0, "false")])
def test_merge_refusal_does_not_dispatch(tmp_path, merge_exit, merge_result):
    merge, deploy, commands = _run_upgrade(
        tmp_path,
        {"checks": [PASS], "merge_exit": merge_exit, "merge_result": merge_result},
    )
    assert merge.returncode != 0
    assert deploy is None
    assert commands[-1][0] == "api"


@pytest.mark.parametrize("failures", [0, 2, 3])
def test_rerun_of_a_merged_upgrade_retries_dispatch(tmp_path, failures):
    merge, deploy, commands = _run_upgrade(
        tmp_path,
        {"views": [{**OPEN, "state": "MERGED"}], "dispatch_failures": failures},
    )
    assert merge.returncode == 0
    assert deploy is not None and (deploy.returncode == 0) == (failures < 3)
    assert sum(command[:2] == ["workflow", "run"] for command in commands) == min(
        failures + 1, 3
    )
    assert not any(command[0] == "api" for command in commands)


def test_renamed_docs_job_can_supply_its_required_context(tmp_path):
    merge, deploy, _ = _run_upgrade(
        tmp_path,
        {"checks": [[{"name": "site / build", "bucket": "pass"}]]},
        docs_check="site / build",
    )
    assert merge.returncode == 0
    assert deploy is not None and deploy.returncode == 0


@pytest.mark.parametrize("wait_minutes", ["0", "46", "1.5", "-1"])
def test_invalid_wait_is_rejected_before_any_github_request(tmp_path, wait_minutes):
    merge, deploy, commands = _run_upgrade(tmp_path, {}, wait_minutes=wait_minutes)
    assert merge.returncode != 0
    assert deploy is None and commands == []
