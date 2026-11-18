"""Checks for CI and CLI canary workflows."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
JOBS = yaml.load(
    (ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader
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


@pytest.mark.parametrize("cli", ["claude", "codex"])
@pytest.mark.parametrize("remote_sha", ["a" * 40, "b" * 40, ""])
def test_canary_checks_remote_main_immediately_before_publishing(
    tmp_path, cli, remote_sha
):
    workflow = yaml.load(
        (ROOT / f".github/workflows/{cli}-plugin-canary.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    freshness, publish = workflow["jobs"]["bump-pin"]["steps"][-2:]
    assert freshness["id"] == "freshness"
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
