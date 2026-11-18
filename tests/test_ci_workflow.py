"""Checks for the CI workflow and its locked agent CLIs."""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
CI_TOOLS = ROOT / ".github/ci-tools"
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
def test_ci_installs_agent_clis_from_the_lockfile(job):
    steps = JOBS[job]["steps"]
    node = next(
        step for step in steps if step.get("uses", "").startswith("actions/setup-node@")
    )
    install = next(
        step for step in steps if step.get("run") == "bash scripts/install-ci-clis.sh"
    )
    assert node["with"]["node-version"] == "22"
    assert steps.index(node) < steps.index(install)
    script = (ROOT / "scripts/install-ci-clis.sh").read_text()
    assert (
        "npm ci" in script and "--engine-strict" in script and "npm view" not in script
    )


def test_only_plugin_install_resolves_the_plugins_cli_version():
    (job,) = (
        name
        for name, job in JOBS.items()
        if any(
            "npm view plugins@latest version" in step.get("run", "")
            for step in job["steps"]
        )
    )
    assert job == "plugin-install"


def test_agent_clis_are_locked_to_exact_versions():
    manifest = json.loads((CI_TOOLS / "package.json").read_text())
    lock = json.loads((CI_TOOLS / "package-lock.json").read_text())
    deps = manifest["dependencies"]
    assert set(deps) == {"@anthropic-ai/claude-code", "@openai/codex"}
    for name, version in deps.items():
        assert version[0].isdigit(), f"{name} must be an exact version"
        assert lock["packages"][f"node_modules/{name}"]["version"] == version


def test_dependabot_updates_agent_clis_daily():
    config = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text())
    (entry,) = [u for u in config["updates"] if u["directory"] == "/.github/ci-tools"]
    assert entry["package-ecosystem"] == "npm"
    assert entry["schedule"]["interval"] == "daily"


def test_auto_merge_is_limited_to_dependabot_ci_tools_updates():
    workflow = yaml.load(
        (WORKFLOWS / "ci-tools-auto-merge.yml").read_text(), Loader=yaml.BaseLoader
    )
    assert workflow["on"]["pull_request"]["branches"] == ["main"]
    job = workflow["jobs"]["enable-auto-merge"]
    assert job["if"] == "github.event.pull_request.user.login == 'dependabot[bot]'"
    meta, merge = job["steps"]
    action, ref = meta["uses"].split("@")
    assert action == "dependabot/fetch-metadata" and len(ref) == 40
    assert merge["if"] == "steps.meta.outputs.directory == '/dot-github/ci-tools'"
    assert merge["run"].startswith("gh pr merge --auto")


@pytest.mark.parametrize("matching_issue", [False, True])
def test_failed_update_creates_one_open_issue_per_branch(tmp_path, matching_issue):
    workflow = yaml.load(
        (WORKFLOWS / "ci-tools-alert.yml").read_text(), Loader=yaml.BaseLoader
    )
    job = workflow["jobs"]["alert"]
    assert (
        job["concurrency"]["group"]
        == "ci-tools-alert-${{ github.event.workflow_run.head_branch }}"
    )

    branch = "dependabot/npm_and_yarn/dot-github/ci-tools/openai/codex-0.171.0"
    title = "CI failed on agent CLI update openai/codex-0.171.0"
    issues = [
        [
            {"title": title, "number": 1, "pull_request": {}},
            {"title": "Other", "number": 2},
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
            "RUN_URL": "https://github.com/allenai/asta-plugins/actions/runs/123",
            "SHA": "abc123",
            "ISSUES": json.dumps(issues),
        },
        capture_output=True,
        check=True,
        text=True,
    )
    expected = ["comment", "3"] if matching_issue else ["create", "--title", title]
    assert result.stdout.splitlines()[: 1 + len(expected)] == ["issue", *expected]
