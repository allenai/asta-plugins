"""Exercise release deployment selection and reporting without GitHub writes."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load(
    (ROOT / ".github/workflows/example-workspace.yml").read_text()
)
REPORT = WORKFLOW["jobs"]["report"]["steps"][0]["run"]
RELEASE = WORKFLOW["jobs"]["deploy"]["steps"][0]["run"]
TITLE = "Example workspace failed to build for v0.109.0"


def reporter(
    tmp_path,
    issues=(),
    *,
    lookup_fails=False,
    build="failure",
    theme="success",
    deploy="skipped",
):
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
        "BUILD_RESULT": build,
        "THEME_RESULT": theme,
        "DEPLOY_RESULT": deploy,
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
        return (
            [json.loads(line) for line in log.read_text().splitlines()]
            if log.exists()
            else []
        )

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


def test_build_failure_preserves_any_existing_site(tmp_path):
    run, calls = reporter(tmp_path)
    assert run(128).returncode == 0
    body = calls()[-1][-1]
    assert "deployment was not attempted" in body
    assert "Any previously published demo is unchanged" in body


def test_browser_failure_reports_that_deployment_was_not_attempted(tmp_path):
    run, calls = reporter(tmp_path, build="success", theme="failure")
    assert run(128).returncode == 0
    body = calls()[-1][-1]
    assert "browser checks failed" in body
    assert "deployment was not attempted" in body


def test_deployment_failure_does_not_claim_the_live_site_is_unchanged(tmp_path):
    run, calls = reporter(tmp_path, build="success", deploy="failure")
    assert run(129).returncode == 0
    body = calls()[-1][-1]
    assert "deployment failed after a successful build" in body
    assert "live site's state is unconfirmed" in body
    assert "unchanged" not in body
    assert "failed to build" not in body


def test_successful_or_superseded_release_does_not_open_an_issue(tmp_path):
    run, calls = reporter(tmp_path, build="success", deploy="success")
    assert run(130).returncode == 0
    assert calls() == []


def release_gate(tmp_path, ref, pages, *, lookup_fails=False):
    gh = tmp_path / "gh"
    gh.write_text(
        f"#!{sys.executable}\n"
        + """import json, os, sys
assert sys.argv[1:] == ["api", "--paginate", "--slurp", "repos/allenai/asta-plugins/tags?per_page=100"]
if os.environ["LOOKUP_FAILS"] == "1":
    sys.exit(22)
print(os.environ["TEST_TAG_PAGES"])
"""
    )
    gh.chmod(0o755)
    output = tmp_path / "output"
    result = subprocess.run(
        ["bash", "-c", RELEASE],
        cwd=tmp_path,
        env={
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "GITHUB_REPOSITORY": "allenai/asta-plugins",
            "GITHUB_OUTPUT": str(output),
            "REF": ref,
            "TEST_TAG_PAGES": json.dumps(
                [[{"name": tag} for tag in page] for page in pages]
            ),
            "LOOKUP_FAILS": "1" if lookup_fails else "0",
        },
        text=True,
        capture_output=True,
        timeout=10,
    )
    return result, output.read_text() if output.exists() else ""


@pytest.mark.parametrize(
    ("ref", "expected"),
    [("v0.9.0", "false"), ("v0.10.0", "true"), ("v0.11.0-rc.1", "false")],
)
def test_only_the_newest_final_tag_deploys_even_when_older_build_finishes_last(
    tmp_path, ref, expected
):
    result, output = release_gate(
        tmp_path, ref, [["v0.11.0-rc.1", "latest", "v0.9.0"], ["v0.10.0"]]
    )
    assert result.returncode == 0, result.stderr
    assert output == f"current={expected}\n"


@pytest.mark.parametrize("pages", [[], [["latest", "v0.11.0-rc.1"]]])
def test_no_final_tags_fails_closed(tmp_path, pages):
    result, output = release_gate(tmp_path, "v0.10.0", pages)
    assert result.returncode != 0
    assert output == ""


def test_unreadable_tags_fail_closed(tmp_path):
    result, output = release_gate(tmp_path, "v0.10.0", [["v0.10.0"]], lookup_fails=True)
    assert result.returncode != 0
    assert output == ""


def test_release_selection_runs_under_the_shared_pages_lock():
    deploy = WORKFLOW["jobs"]["deploy"]
    assert deploy["concurrency"] == {
        "group": "pages",
        "cancel-in-progress": False,
        "queue": "max",
    }
    assert deploy["steps"][0]["id"] == "release"
    assert deploy["steps"][1]["if"] == "steps.release.outputs.current == 'true'"


def test_shared_asset_changes_trigger_the_example_check():
    # PyYAML's YAML 1.1 loader interprets the GitHub Actions key 'on' as True.
    paths = WORKFLOW[True]["pull_request"]["paths"]
    assert "plugins/asta-tools/skills/workspace/assets/**" in paths


def test_example_preview_runs_only_for_rendered_paths_through_the_shared_workflow():
    import yaml

    root = Path(__file__).resolve().parents[1]
    wf = yaml.safe_load((root / ".github/workflows/example-preview.yml").read_text())
    trigger = wf[True]["pull_request"]  # PyYAML reads the `on:` key as True
    assert trigger["types"] == ["opened", "synchronize", "reopened", "closed"]
    paths = trigger["paths"]
    assert "examples/workspace/**" in paths
    assert "plugins/asta-tools/skills/workspace/assets/**" in paths
    assert not any(
        p.startswith("plugins/asta-tools/skills/workspace/SKILL") for p in paths
    )
    job = wf["jobs"]["docs"]
    assert job["uses"] == "./.github/workflows/workspace-quarto-site.yml"
    assert job["with"]["site-dir"] == "examples/workspace"

    shared = yaml.safe_load(
        (root / ".github/workflows/workspace-quarto-site.yml").read_text()
    )
    assert shared[True]["workflow_call"]["inputs"]["site-dir"]["default"] == "."
    build = shared["jobs"]["build"]
    assert build["defaults"]["run"]["working-directory"] == "${{ inputs.site-dir }}"


def pages_builder(tmp_path, config, statuses=("built",)):
    log = tmp_path / "calls.jsonl"
    gh = tmp_path / "gh"
    gh.write_text(
        f"#!{sys.executable}\n"
        + "import json, sys\nfrom pathlib import Path\n"
        + f"log = Path({str(log)!r})\n"
        + f"config = {config!r}\nstatuses = {list(statuses)!r}\n"
        + "args = sys.argv[1:]\n"
        + "calls = log.read_text().splitlines() if log.exists() else []\n"
        + "with log.open('a') as out: out.write(json.dumps(args) + '\\n')\n"
        + "if args == ['api', 'repos/owner/project/pages']: print(json.dumps(config))\n"
        + "elif args == ['api', '--method', 'POST', 'repos/owner/project/pages/builds', '--jq', '.url']: print('https://api.github.com/build/123')\n"
        + "elif args == ['api', 'https://api.github.com/build/123', '--jq', '.status']:\n"
        + "    polls = sum('https://api.github.com/build/123' in json.loads(call) for call in calls)\n"
        + "    print(statuses[min(polls, len(statuses) - 1)])\n"
        + "else: raise AssertionError(args)\n"
    )
    gh.chmod(0o755)
    sleep = tmp_path / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n")
    sleep.chmod(0o755)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/request-example-pages-build.sh")],
        env={"PATH": f"{tmp_path}:/usr/bin:/bin", "GITHUB_REPOSITORY": "owner/project"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result, [json.loads(line) for line in log.read_text().splitlines()]


@pytest.mark.parametrize(
    "config",
    [
        {"build_type": "workflow", "source": {"branch": "main", "path": "/"}},
        {"build_type": "legacy", "source": {"branch": "other", "path": "/"}},
        {"build_type": "legacy", "source": {"branch": "gh-pages", "path": "/docs"}},
    ],
)
def test_pages_build_waits_for_the_operator_source_switch(tmp_path, config):
    result, calls = pages_builder(tmp_path, config)
    assert result.returncode == 0, result.stderr
    assert calls == [["api", "repos/owner/project/pages"]]


def test_pages_build_explicitly_publishes_bot_push_and_waits(tmp_path):
    result, calls = pages_builder(
        tmp_path,
        {
            "build_type": "legacy",
            "source": {"branch": "gh-pages", "path": "/"},
        },
        ("queued", "building", "built"),
    )
    assert result.returncode == 0, result.stderr
    assert sum("POST" in call for call in calls) == 1
    assert len(calls) == 5


@pytest.mark.parametrize("status", ["errored", "building"])
def test_pages_build_surfaces_failure_or_timeout(tmp_path, status):
    result, _ = pages_builder(
        tmp_path,
        {
            "build_type": "legacy",
            "source": {"branch": "gh-pages", "path": "/"},
        },
        (status,),
    )
    assert result.returncode == 1
    assert "::error::" in result.stdout


def test_preview_updates_cleanup_and_releases_request_pages_publication():
    preview = yaml.safe_load(
        (ROOT / ".github/workflows/example-preview.yml").read_text()
    )
    publish = preview["jobs"]["publish-pages"]
    assert publish["needs"] == "docs"
    assert "closed" not in publish["if"]
    assert "head.repo.full_name == github.repository" in publish["if"]
    assert publish["permissions"] == {"contents": "read", "pages": "write"}
    assert publish["steps"][-1]["run"] == "bash scripts/request-example-pages-build.sh"
    release = WORKFLOW["jobs"]["publish-gh-pages"]
    assert "needs.deploy.outputs.current == 'true'" in release["if"]
    assert release["steps"][-1]["run"] == "bash scripts/request-example-pages-build.sh"


def test_fork_builds_stay_read_only_and_never_try_to_publish():
    shared = yaml.safe_load(
        (ROOT / ".github/workflows/workspace-quarto-site.yml").read_text()
    )
    assert shared["jobs"]["build"]["permissions"] == {"contents": "read"}
    assert "head.repo.full_name != github.repository" in shared["jobs"]["deploy"]["if"]
    assert (
        "head.repo.full_name == github.repository"
        in shared["jobs"]["cleanup-preview"]["if"]
    )
    assert (
        "head.repo.full_name != github.repository"
        in shared["jobs"]["preview-unavailable"]["if"]
    )
