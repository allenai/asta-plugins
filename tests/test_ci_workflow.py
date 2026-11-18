"""Checks for CI and CLI canary workflows."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
JOBS = yaml.load((WORKFLOWS / "ci.yml").read_text(), Loader=yaml.BaseLoader)["jobs"]
PIN_JOBS = yaml.load(
    (WORKFLOWS / "cli-pin-maintenance.yml").read_text(), Loader=yaml.BaseLoader
)["jobs"]


def test_tests_ok_needs_every_per_python_job():
    per_python = {
        name
        for name, job in JOBS.items()
        if "python-version" in job.get("strategy", {}).get("matrix", {})
    }
    gate = JOBS["tests-ok"]
    needs = gate["needs"]
    assert per_python and per_python <= set(
        [needs] if isinstance(needs, str) else needs
    )
    assert gate["if"] == "always()"
    assert gate["steps"][-1]["env"]["RESULT"] == "${{ needs.test.result }}"


def test_code_quality_runs_on_x86_for_every_build_runner():
    # The shellcheck action installs an x86_64 binary, so code-quality on the
    # release checks' arm build-runner fails before checking anything.
    assert JOBS["code-quality"]["runs-on"] == "ubuntu-latest"


@pytest.mark.parametrize("result", ["success", "failure", "cancelled", "skipped"])
def test_tests_ok_passes_only_on_success(result):
    step = JOBS["tests-ok"]["steps"][-1]
    run = subprocess.run(
        ["bash", "-c", step["run"]],
        env=dict(os.environ, RESULT=result),
        capture_output=True,
    )
    assert (run.returncode == 0) == (result == "success")


@pytest.mark.parametrize(
    ("cli", "format_version"),
    [("claude-code", "{} (Claude Code)"), ("codex", "codex-cli {}")],
)
@pytest.mark.parametrize(
    ("version", "stable"),
    [("1.2.3", True), ("1.2.3-rc.1", False), ("1.2.3+build.1", False)],
)
def test_cli_version_parser_requires_a_stable_release(
    cli, format_version, version, stable
):
    result = subprocess.run(
        [
            "bash",
            ROOT / "scripts/parse-cli-version.sh",
            cli,
            format_version.format(version),
        ],
        capture_output=True,
        text=True,
    )
    if stable:
        assert result.returncode == 0, result.stderr
        assert result.stdout == f"{version}\n"
    else:
        assert result.returncode != 0
        assert result.stdout == ""
        assert version in result.stderr


@pytest.mark.parametrize("remote_sha", ["a" * 40, "b" * 40, ""])
def test_pin_maintenance_checks_remote_main_immediately_before_publishing(
    tmp_path, remote_sha
):
    steps = PIN_JOBS["bump-pin"]["steps"]
    freshness = next(step for step in steps if step.get("id") == "freshness")
    publish = next(step for step in steps if step.get("id") == "publish")
    assert steps.index(publish) == steps.index(freshness) + 1
    assert publish["if"] == "steps.freshness.outputs.current == 'true'"
    output = tmp_path / "output"
    summary = tmp_path / "summary"
    output.touch()
    tested_sha = "a" * 40
    gh_stub = r"""gh() {
      [[ "$1" == api && "$*" == *repos/owner/repo/git/ref/heads/main* && -n "$REMOTE_SHA" ]] || return 1
      printf '%s\n' "$REMOTE_SHA"
    }
    """
    result = subprocess.run(
        ["bash", "-eo", "pipefail", "-c", gh_stub + freshness["run"]],
        env={
            "PATH": os.environ["PATH"],
            "GITHUB_REPOSITORY": "owner/repo",
            "TESTED_SHA": tested_sha,
            "REMOTE_SHA": remote_sha,
            "GITHUB_OUTPUT": str(output),
            "GITHUB_STEP_SUMMARY": str(summary),
        },
        capture_output=True,
    )
    if remote_sha == tested_sha:
        assert result.returncode == 0, result.stderr
        assert output.read_text() == "current=true\n"
    elif remote_sha:
        assert result.returncode == 0, result.stderr
        assert output.read_text() == ""
        assert "Skipping publication" in summary.read_text()
    else:
        assert result.returncode != 0
        assert output.read_text() == ""


@pytest.mark.parametrize(
    ("cli_name", "bump_result", "setup_failure", "failed_checks", "failure"),
    [
        ("Claude Code", "failure", "", "", "pin bump"),
        ("Codex", "failure", "", "", "pin bump"),
        ("Claude Code", "skipped", "uv setup", "", "uv setup"),
        (
            "Claude Code",
            "skipped",
            "",
            "selective install, skill descriptions, ",
            "selective install, skill descriptions",
        ),
        (
            "Codex",
            "skipped",
            "",
            "plugin install and skill descriptions",
            "plugin install and skill descriptions",
        ),
        ("Codex", "skipped", "", "", "unexpected canary failure"),
    ],
)
def test_pin_maintenance_alert_reports_the_failed_job(
    cli_name, bump_result, setup_failure, failed_checks, failure
):
    alert = PIN_JOBS["alert"]
    assert alert["needs"] == "bump-pin"
    assert "needs.bump-pin.result == 'failure'" in alert["if"]
    assert "inputs.canary-result == 'failure'" in alert["if"]
    run = run_alert(cli_name, bump_result, setup_failure, failed_checks)
    assert run.returncode == 0, run.stderr
    assert f"Created: {cli_name} 1.2.3 canary failed: {failure}" in run.stdout
    assert f"- Failure: {failure}" in run.stdout
    assert "- Run: https://github.com/owner/repo/actions/runs/123" in run.stdout
    assert ("compatibility checks passed" in run.stdout) == (bump_result == "failure")


def test_pin_maintenance_deduplicates_pin_bump_alerts():
    title = "Codex 1.2.3 canary failed: pin bump"
    run = run_alert("Codex", "failure", "", "", prior_issue_title=title)
    assert run.returncode == 0, run.stderr
    assert run.stdout == f"Already reported: {title}\n"


def run_alert(
    cli_name, bump_result, setup_failure, failed_checks, prior_issue_title=""
):
    gh_stub = r"""gh() {
      if [ "$1" = api ]; then
        [[ "$*" == *'issues?state=all&per_page=100'* ]] || return 1
        printf '%s\n' "$PRIOR_ISSUE_TITLE"
      elif [ "$1 $2" = 'issue create' ]; then
        [[ "$3 $4 $5 $7 $8" == '--repo owner/repo --title --body-file -' ]] || return 1
        printf 'Created: %s\n' "$6"
        cat
      else
        return 1
      fi
    }
    """
    return subprocess.run(
        [
            "bash",
            "-eo",
            "pipefail",
            "-c",
            gh_stub + PIN_JOBS["alert"]["steps"][0]["run"],
        ],
        env={
            "PATH": os.environ["PATH"],
            "GITHUB_REPOSITORY": "owner/repo",
            "CLI_NAME": cli_name,
            "VERSION": "1.2.3",
            "SETUP_FAILURE": setup_failure,
            "FAILED_CHECKS": failed_checks,
            "BUMP_RESULT": bump_result,
            "RUN_URL": "https://github.com/owner/repo/actions/runs/123",
            "PRIOR_ISSUE_TITLE": prior_issue_title,
        },
        capture_output=True,
        text=True,
    )
