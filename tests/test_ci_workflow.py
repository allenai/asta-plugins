"""Checks for the CI workflow and its locked agent CLIs."""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
CI_TOOLS = ROOT / "ci-tools"
JOBS = yaml.load((WORKFLOWS / "ci.yml").read_text(), Loader=yaml.BaseLoader)["jobs"]


def _needs(job):
    needs = job["needs"]
    return {needs} if isinstance(needs, str) else set(needs)


def test_tests_ok_needs_every_per_python_job_and_plugin_install():
    per_python = {
        name
        for name, job in JOBS.items()
        if "python-version" in job.get("strategy", {}).get("matrix", {})
    }
    gate = JOBS["tests-ok"]
    assert per_python and per_python | {"plugin-install"} <= _needs(gate)
    assert gate["if"] == "always()"
    env = gate["steps"][-1]["env"]
    assert env["TEST_RESULT"] == "${{ needs.test.result }}"
    assert env["INSTALL_RESULT"] == "${{ needs.plugin-install.result }}"


def test_code_quality_runs_on_x86_for_every_build_runner():
    # The shellcheck action installs an x86_64 binary, so code-quality on the
    # release checks' arm build-runner fails before checking anything.
    assert JOBS["code-quality"]["runs-on"] == "ubuntu-latest"


def test_workflows_disable_claude_code_background_updates():
    for job in (JOBS["test"], JOBS["plugin-install"]):
        assert job["env"]["DISABLE_AUTOUPDATER"] == "1"


def test_claude_selective_install_runs_in_ci():
    steps = JOBS["test"]["steps"]
    (test_step,) = (step for step in steps if step.get("run") == "make test-plugins")
    assert test_step["env"]["ASTA_TEST_CLAUDE_PLUGIN_DEPS"] == "1"


@pytest.mark.parametrize("test_result", ["success", "failure", "skipped"])
@pytest.mark.parametrize("install_result", ["success", "failure", "cancelled"])
def test_tests_ok_passes_only_when_both_succeed(test_result, install_result):
    step = JOBS["tests-ok"]["steps"][-1]
    run = subprocess.run(
        ["bash", "-c", step["run"]],
        env=dict(os.environ, TEST_RESULT=test_result, INSTALL_RESULT=install_result),
        capture_output=True,
    )
    assert (run.returncode == 0) == (test_result == install_result == "success")


@pytest.mark.parametrize("job", ["test", "plugin-install"])
def test_ci_installs_cli_tools_from_the_lockfile_with_read_only_access(job):
    job = JOBS[job]
    steps = job["steps"]
    checkout = next(
        step for step in steps if step.get("uses", "").startswith("actions/checkout@")
    )
    node = next(
        step for step in steps if step.get("uses", "").startswith("actions/setup-node@")
    )
    install = next(
        step for step in steps if step.get("run") == "bash scripts/install-ci-clis.sh"
    )
    assert node["with"]["node-version"] == "22"
    assert steps.index(node) < steps.index(install)
    assert job["permissions"] == {"contents": "read"}
    assert checkout["with"]["persist-credentials"] == "false"
    script = (ROOT / "scripts/install-ci-clis.sh").read_text()
    assert (
        "npm ci" in script and "--engine-strict" in script and "npm view" not in script
    )


def test_plugin_install_uses_the_locked_plugins_binary():
    assert JOBS["plugin-install"]["env"]["PLUGINS_CLI_BIN"] == (
        "${{ github.workspace }}/ci-tools/node_modules/.bin/plugins"
    )


def test_cli_tools_are_locked_to_exact_versions():
    manifest = json.loads((CI_TOOLS / "package.json").read_text())
    lock = json.loads((CI_TOOLS / "package-lock.json").read_text())
    deps = manifest["dependencies"]
    assert set(deps) == {"@anthropic-ai/claude-code", "@openai/codex", "plugins"}
    for name, version in deps.items():
        assert re.fullmatch(r"\d+\.\d+\.\d+", version), f"{name} must be pinned"
        assert lock["packages"][f"node_modules/{name}"]["version"] == version


def test_dependabot_checks_for_cli_updates_every_day_without_a_cooldown():
    config = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text())
    (entry,) = [u for u in config["updates"] if u["directory"] == "/ci-tools"]
    assert entry["package-ecosystem"] == "npm"
    assert entry["schedule"]["interval"] == "cron"
    assert entry["schedule"]["cronjob"].split()[2:] == ["*", "*", "*"]
    assert entry["cooldown"]["default-days"] == 0


def test_auto_merge_is_limited_to_dependabot_ci_tools_updates():
    workflow = yaml.load(
        (WORKFLOWS / "ci-tools-auto-merge.yml").read_text(), Loader=yaml.BaseLoader
    )
    assert workflow["on"]["pull_request"]["branches"] == ["main"]
    job = workflow["jobs"]["enable-auto-merge"]
    assert job["if"].split(" && ") == [
        "github.actor == 'dependabot[bot]'",
        "github.event.pull_request.user.login == 'dependabot[bot]'",
        "github.event.pull_request.head.repo.full_name == github.repository",
    ]
    meta, merge = job["steps"]
    action, ref = meta["uses"].split("@")
    assert action == "dependabot/fetch-metadata" and len(ref) == 40
    assert merge["if"] == "steps.meta.outputs.directory == '/ci-tools'"
    assert merge["run"].startswith("gh pr merge --auto")
    assert '--match-head-commit "$HEAD_SHA"' in merge["run"]
    assert merge["env"]["HEAD_SHA"] == "${{ github.event.pull_request.head.sha }}"


def test_alerts_are_limited_to_completed_ci_tools_updates():
    workflow = yaml.load(
        (WORKFLOWS / "ci-tools-alert.yml").read_text(), Loader=yaml.BaseLoader
    )
    job = workflow["jobs"]["alert"]
    condition = job["if"].removeprefix("${{ ").removesuffix(" }}")
    assert re.split(r"\s+&&\s+", condition) == [
        'contains(fromJSON(\'["failure","timed_out","success"]\'), '
        "github.event.workflow_run.conclusion)",
        "github.event.workflow_run.event == 'pull_request'",
        "github.event.workflow_run.actor.login == 'dependabot[bot]'",
        "github.event.workflow_run.head_repository.full_name == github.repository",
        "startsWith(github.event.workflow_run.head_branch, "
        "'dependabot/npm_and_yarn/ci-tools/')",
    ]


@pytest.mark.parametrize(
    ("conclusion", "matching_issue", "expected"),
    [
        (
            "failure",
            False,
            ["create", "--title", "CLI update stuck: openai/codex"],
        ),
        ("timed_out", True, ["comment", "3"]),
        ("success", True, ["close", "3"]),
        ("success", False, []),
    ],
)
@pytest.mark.parametrize("version", ["0.171.0", "1.0.0-alpha.1"])
def test_update_failures_share_one_issue_per_cli(
    tmp_path, conclusion, matching_issue, expected, version
):
    workflow = yaml.load(
        (WORKFLOWS / "ci-tools-alert.yml").read_text(), Loader=yaml.BaseLoader
    )
    job = workflow["jobs"]["alert"]
    assert job["concurrency"] == {"group": "ci-tools-alert", "queue": "max"}

    # Any release of the CLI finds the issue an earlier release opened.
    branch = f"dependabot/npm_and_yarn/ci-tools/openai/codex-{version}"
    title = "CLI update stuck: openai/codex"
    issues = [
        [
            {"title": title, "number": 1, "pull_request": {}},
            {"title": "CLI update stuck: anthropic-ai/claude-code", "number": 2},
        ]
    ]
    if matching_issue:
        issues.append([{"title": title, "number": 3}])
    gh = tmp_path / "gh"
    gh.write_text(
        '#!/bin/bash\nif [[ "$1" == api ]]; then\n'
        '  printf "%s\\n" "$ISSUES"\nelse\n  printf "%s\\n" "$@"\nfi\n'
    )
    gh.chmod(0o755)
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", job["steps"][0]["run"]],
        env={
            "PATH": f"{tmp_path}{os.pathsep}{os.defpath}",
            "GH_REPO": "allenai/asta-plugins",
            "BRANCH": branch,
            "CONCLUSION": conclusion,
            "RUN_URL": "https://github.com/allenai/asta-plugins/actions/runs/123",
            "SHA": "abc123",
            "ISSUES": json.dumps(issues),
        },
        capture_output=True,
        check=True,
        text=True,
    )
    lines = result.stdout.splitlines()
    assert lines[: 1 + len(expected)] == (["issue", *expected] if expected else [])
    if conclusion != "success":
        assert f"CI result: `{conclusion}`" in result.stdout


def test_freshness_runs_after_dependabot_and_shares_the_alert_queue():
    workflow = yaml.load(
        (WORKFLOWS / "ci-tools-freshness.yml").read_text(), Loader=yaml.BaseLoader
    )
    (schedule,) = workflow["on"]["schedule"]
    config = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text())
    (entry,) = [u for u in config["updates"] if u["directory"] == "/ci-tools"]
    dependabot_minute, dependabot_hour = entry["schedule"]["cronjob"].split()[:2]
    minute, hour = schedule["cron"].split()[:2]
    assert schedule["cron"].split()[2:] == ["*", "*", "*"]
    assert (int(hour) - int(dependabot_hour)) * 60 + int(minute) - int(
        dependabot_minute
    ) >= 2 * 60
    job = workflow["jobs"]["freshness"]
    assert job["concurrency"] == {"group": "ci-tools-alert", "queue": "max"}


@pytest.mark.parametrize(
    ("latest", "hours_ago", "issue", "commented", "expected"),
    [
        ("0.170.0", 100, True, False, ["close", "3"]),
        ("0.170.0", 100, False, False, []),
        ("0.171.0", 2, False, False, []),
        (
            "0.171.0",
            30,
            False,
            False,
            ["create", "--title", "CLI update stuck: openai/codex"],
        ),
        ("0.171.0", 30, True, False, ["comment", "3"]),
        ("0.171.0", 30, True, True, []),
    ],
)
def test_freshness_alerts_once_when_main_lags_a_release(
    tmp_path, latest, hours_ago, issue, commented, expected
):
    workflow = yaml.load(
        (WORKFLOWS / "ci-tools-freshness.yml").read_text(), Loader=yaml.BaseLoader
    )
    step = workflow["jobs"]["freshness"]["steps"][-1]
    (tmp_path / "ci-tools").mkdir()
    (tmp_path / "ci-tools/package.json").write_text(
        json.dumps({"dependencies": {"@openai/codex": "0.170.0"}})
    )
    published = subprocess.run(
        ["date", "-u", "-d", f"{hours_ago} hours ago", "+%Y-%m-%dT%H:%M:%SZ"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    title = "CLI update stuck: openai/codex"
    issues = [[{"title": title, "number": 1, "pull_request": {}}]]
    if issue:
        issues.append([{"title": title, "number": 3}])
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "npm").write_text(
        '#!/bin/bash\nif [[ "$3" == time ]]; then printf "%s\\n" "$TIMES"; '
        'else printf "%s\\n" "$LATEST"; fi\n'
    )
    (bin_dir / "gh").write_text(
        '#!/bin/bash\nif [[ "$1" == api && "$*" == */comments* ]]; then\n'
        '  printf "%s\\n" "$COMMENTS"\nelif [[ "$1" == api ]]; then\n'
        '  printf "%s\\n" "$ISSUES"\nelse\n  printf "%s\\n" "$@"\nfi\n'
    )
    for tool in ("npm", "gh"):
        (bin_dir / tool).chmod(0o755)
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=tmp_path,
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "GH_REPO": "allenai/asta-plugins",
            "RUN_URL": "https://github.com/allenai/asta-plugins/actions/runs/123",
            "GRACE_HOURS": step["env"]["GRACE_HOURS"],
            "LATEST": latest,
            "TIMES": json.dumps({latest: published}),
            "ISSUES": json.dumps(issues),
            "COMMENTS": "`@openai/codex@0.171.0` was released" if commented else "",
        },
        capture_output=True,
        check=True,
        text=True,
    )
    lines = result.stdout.splitlines()
    if expected:
        assert lines[: 1 + len(expected)] == ["issue", *expected]
    else:
        assert len(lines) == 1
    stale = latest != "0.170.0" and hours_ago >= 26
    assert lines[-1] == f"stale={int(stale)}"
    if expected[:1] in (["create"], ["comment"]):
        assert "`@openai/codex@0.171.0` was released 30 hours ago" in result.stdout
        assert "still locks `0.170.0`" in result.stdout
