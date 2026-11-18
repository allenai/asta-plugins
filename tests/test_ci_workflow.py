"""Checks for the CI workflow and its locked agent CLIs."""

import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
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


def test_freshness_runs_after_dependabot_and_is_the_only_issue_writer():
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
    assert job["concurrency"] == {"group": "ci-tools-freshness"}
    assert not (WORKFLOWS / "ci-tools-alert.yml").exists()
    checkout, check = job["steps"]
    assert checkout["with"]["ref"] == "refs/heads/main"
    assert (
        check["env"]["DEPENDABOT_CHECK_UTC"]
        == f"{dependabot_hour.zfill(2)}:{dependabot_minute}"
    )
    assert (int(hour) - int(dependabot_hour)) * 60 + int(minute) - int(
        dependabot_minute
    ) >= int(check["env"]["GRACE_HOURS"]) * 60


def _run_freshness(tmp_path, now, packages, metadata, issues):
    workflow = yaml.load(
        (WORKFLOWS / "ci-tools-freshness.yml").read_text(), Loader=yaml.BaseLoader
    )
    step = workflow["jobs"]["freshness"]["steps"][-1]
    (tmp_path / "ci-tools").mkdir()
    (tmp_path / "ci-tools/package-lock.json").write_text(
        json.dumps(
            {
                "packages": {
                    "": {"dependencies": packages},
                    **{
                        f"node_modules/{name}": {"version": version}
                        for name, version in packages.items()
                    },
                }
            }
        )
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "npm").write_text(
        '#!/bin/bash\njq -er --arg pkg "$2" \'.[$pkg] // empty\' <<< "$METADATA"\n'
    )
    (bin_dir / "date").write_text(
        '#!/bin/bash\nif [[ "$2" == +%s ]]; then printf "%s\\n" "$NOW"; '
        'else /usr/bin/date -u -d "2026-11-18 $3" +%s; fi\n'
    )
    (bin_dir / "gh").write_text(
        '#!/bin/bash\nif [[ "$1" == api ]]; then\n'
        '  printf "%s\\n" "$ISSUES"\nelse\n  printf "%s\\n" "$@"\nfi\n'
    )
    for tool in ("npm", "gh", "date"):
        (bin_dir / tool).chmod(0o755)
    return subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=tmp_path,
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "GH_REPO": "allenai/asta-plugins",
            "RUN_URL": "https://github.com/allenai/asta-plugins/actions/runs/123",
            "DEPENDABOT_CHECK_UTC": step["env"]["DEPENDABOT_CHECK_UTC"],
            "GRACE_HOURS": step["env"]["GRACE_HOURS"],
            "NOW": str(int(now.timestamp())),
            "METADATA": json.dumps(metadata),
            "ISSUES": json.dumps(issues),
        },
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    ("latest", "hours_ago", "issue", "other_releases", "run_hour", "expected"),
    [
        ("0.170.0", 100, True, {}, 12, ["close", "3"]),
        ("0.170.0", 100, False, {}, 12, []),
        # A newer release still inside the grace window does not keep it open.
        ("0.172.0", 2, True, {}, 12, ["close", "3"]),
        ("0.171.0", 2, False, {"0.171.0-alpha.1": 30}, 12, []),
        ("0.171.0", 4, False, {}, 10, []),
        (
            "0.171.0",
            4,
            False,
            {},
            12,
            ["create", "--title", "CLI update stuck: openai/codex"],
        ),
        ("0.171.0", 30, True, {}, 12, ["edit", "3", "--body"]),
        ("0.172.0", 2, True, {"0.171.0": 30}, 12, ["edit", "3", "--body"]),
    ],
)
def test_freshness_owns_one_issue_per_cli(
    tmp_path, latest, hours_ago, issue, other_releases, run_hour, expected
):
    now = datetime(2026, 11, 18, run_hour, 17, tzinfo=UTC)
    times = {
        version: (now - timedelta(hours=age)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        for version, age in {latest: hours_ago, **other_releases}.items()
    }
    title = "CLI update stuck: openai/codex"
    issues = [[{"title": title, "number": 1, "pull_request": {}}]]
    if issue:
        issues.append([{"title": title, "number": 3}])
    result = _run_freshness(
        tmp_path,
        now,
        {"@openai/codex": "0.170.0"},
        {"@openai/codex": {"dist-tags.latest": latest, "time": times}},
        issues,
    )
    result.check_returncode()
    lines = result.stdout.splitlines()
    if expected:
        assert lines[: 1 + len(expected)] == ["issue", *expected]
    else:
        assert not lines
    if expected[:1] in (["create"], ["edit"]):
        assert "`@openai/codex@0.171.0` was available" in result.stdout
        assert "still locks `0.170.0`" in result.stdout


@pytest.mark.parametrize(
    ("claude_metadata", "code", "annotation"),
    [
        (None, 1, "::error::Could not read npm metadata"),
        ("{invalid json", 1, "::error::Could not read npm metadata"),
        (
            {"dist-tags.latest": "2.1.327"},
            1,
            "::error::Could not read npm release times",
        ),
        (
            {"dist-tags.latest": "2.1.327", "time": {}},
            1,
            "::error::Could not read npm release times",
        ),
        (
            {
                "dist-tags.latest": "2.1.327",
                "time": {"2.1.325": "2026-11-17T07:00:00.000Z"},
            },
            1,
            "::error::Could not read npm release times",
        ),
        (
            {"dist-tags.latest": "2.1.327", "time": {"2.1.327": "invalid"}},
            1,
            "::error::Could not read npm release times",
        ),
        (
            {"dist-tags.latest": "2.1.327-beta.1"},
            0,
            "::warning::npm has no stable latest tag",
        ),
        ({"time": {}}, 0, "::warning::npm has no stable latest tag"),
    ],
)
def test_freshness_checks_codex_even_when_claude_metadata_is_unavailable(
    tmp_path, claude_metadata, code, annotation
):
    claude = "@anthropic-ai/claude-code"
    codex = "@openai/codex"
    result = _run_freshness(
        tmp_path,
        datetime(2026, 11, 18, 12, 17, tzinfo=UTC),
        {claude: "2.1.325", codex: "0.170.0"},
        {
            claude: claude_metadata,
            codex: {
                "dist-tags.latest": "0.171.0",
                "time": {"0.171.0": "2026-11-18T07:00:00.000Z"},
            },
        },
        [[{"title": "CLI update stuck: anthropic-ai/claude-code", "number": 3}]],
    )
    assert result.returncode == code
    lines = result.stdout.splitlines()
    assert lines.count("issue") == 1
    assert lines[:5] == [
        f"{annotation} for {claude}.",
        "issue",
        "create",
        "--title",
        "CLI update stuck: openai/codex",
    ]
