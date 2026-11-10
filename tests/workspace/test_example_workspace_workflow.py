"""The example dogfoods workspace publication; releases only validate."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    return yaml.load(
        (ROOT / f".github/workflows/{name}.yml").read_text(), Loader=yaml.BaseLoader
    )


@pytest.mark.parametrize(
    "files,expected",
    [
        ([{"filename": "examples/workspace/slides/attention/slides.qmd"}], "true"),
        ([{"filename": "examples/workspace-demo.patch"}], "true"),
        ([{"filename": "scripts/build-workspace-demo.py"}], "true"),
        ([{"filename": "plugins/asta-tools/skills/workspace/SKILL.md"}], "true"),
        (
            [
                {
                    "filename": "elsewhere.qmd",
                    "previous_filename": "examples/workspace/old.qmd",
                }
            ],
            "true",
        ),
        (
            [
                {
                    "filename": "plugins/asta-tools/skills/workspace/assets/asta-slides/theme.scss"
                }
            ],
            "true",
        ),
    ],
)
def test_shared_scope_matches_current_and_previous_paths(tmp_path, files, expected):
    result, output = _run_shared_scope(tmp_path, files)
    assert result.returncode == 0, result.stderr
    assert output.read_text() == f"render={expected}\n"


def _run_shared_scope(tmp_path, files, *, site_dir=None, patterns=None):
    workflow = load("workspace-quarto-site")
    script = workflow["jobs"]["scope"]["steps"][0]["run"]
    fake = tmp_path / "gh"
    # Paginated API responses are slurped into one array of pages.
    pages = [files[i : i + 100] for i in range(0, len(files), 100)] or [[]]
    response = tmp_path / "files.json"
    response.write_text(json.dumps(pages))
    fake.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "assert '--paginate' in sys.argv and '--slurp' in sys.argv\n"
        f"print(open({str(response)!r}).read())\n"
    )
    fake.chmod(0o755)
    output = tmp_path / "out"
    env = dict(
        os.environ,
        PATH=f"{tmp_path}:{os.environ['PATH']}",
        EVENT="pull_request",
        ACTION="synchronize",
        SITE_DIR="examples/workspace",
        RENDER_PATHS="**",
        GITHUB_OUTPUT=str(output),
        GITHUB_REPOSITORY="owner/repo",
        PR_NUMBER="1",
    )
    if site_dir is not None:
        env["SITE_DIR"] = site_dir
    if patterns is not None:
        env["RENDER_PATHS"] = patterns
    result = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True
    )
    return result, output


@pytest.mark.parametrize(
    "site,path,expected",
    [
        (".config/site", ".config/site/index.qmd", "true"),
        (".config/site", "config/site/index.qmd", "false"),
        ("site.", "site./index.qmd", "true"),
        ("site.", "site/index.qmd", "false"),
        ("./research/site/", "research/site/index.qmd", "true"),
        ("research/../site", "site/index.qmd", "true"),
        (".", "anywhere/index.qmd", "true"),
    ],
)
def test_default_scope_preserves_real_directory_names(tmp_path, site, path, expected):
    result, output = _run_shared_scope(
        tmp_path, [{"filename": path}], site_dir=site, patterns=""
    )
    assert result.returncode == 0, result.stderr
    assert output.read_text() == f"render={expected}\n"


@pytest.mark.parametrize("site", ["..", "../site", "site/../../outside", "/site"])
@pytest.mark.parametrize("patterns", ["", "**"])
def test_scope_rejects_site_outside_repository(tmp_path, site, patterns):
    result, output = _run_shared_scope(tmp_path, [], site_dir=site, patterns=patterns)
    assert result.returncode != 0
    assert "site-dir must stay inside" in result.stderr
    assert not output.exists()


def test_shipped_caller_grants_scope_and_comment_cleanup_permissions():
    caller = yaml.load(
        (ROOT / "plugins/asta-tools/skills/workspace/assets/docs.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert caller["permissions"]["pull-requests"] == "write"
    shared = load("workspace-quarto-site")
    assert shared["jobs"]["scope"]["permissions"]["pull-requests"] == "read"
    assert shared["jobs"]["cleanup-preview"]["permissions"]["pull-requests"] == "write"


@pytest.mark.parametrize("count", [3000, 3001])
@pytest.mark.parametrize("matches_site", [False, True])
def test_shared_scope_refuses_potentially_truncated_file_list(
    tmp_path, count, matches_site
):
    files = [{"filename": f"unrelated/{i}.txt"} for i in range(count)]
    if matches_site:
        files[0] = {"filename": "examples/workspace/index.qmd"}
    result, output = _run_shared_scope(tmp_path, files)
    assert result.returncode != 0
    assert "3,000-file limit" in result.stderr
    # No false output can trigger deletion; no true output can publish a
    # partially classified PR. The required browser check reports the failure.
    assert not output.exists()


@pytest.mark.parametrize("matches_site", [False, True])
def test_shared_scope_reads_all_pages_below_file_limit(tmp_path, matches_site):
    files = [{"filename": f"unrelated/{i}.txt"} for i in range(2999)]
    if matches_site:
        files[-1] = {"filename": "examples/workspace/index.qmd"}
    result, output = _run_shared_scope(
        tmp_path, files, patterns="examples/workspace/**"
    )
    assert result.returncode == 0, result.stderr
    assert output.read_text() == f"render={str(matches_site).lower()}\n"


@pytest.mark.parametrize(
    "event,action,expected",
    [
        ("pull_request", "closed", "false"),
        ("push", "", "true"),
    ],
)
def test_close_needs_no_file_lookup_and_main_always_builds(
    tmp_path, event, action, expected
):
    script = load("workspace-quarto-site")["jobs"]["scope"]["steps"][0]["run"]
    output = tmp_path / "out"
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        env=dict(os.environ, EVENT=event, ACTION=action, GITHUB_OUTPUT=str(output)),
    )
    assert output.read_text() == f"render={expected}\n"


def test_example_has_one_publisher_and_unfiltered_close():
    site = load("example-preview")
    assert "closed" in site["on"]["pull_request"]["types"]
    assert site["jobs"]["docs-arm"]["with"]["publish"] == "false"


def test_open_pr_that_stops_changing_the_site_loses_its_preview(tmp_path):
    shared = load("workspace-quarto-site")
    cleanup = shared["jobs"]["cleanup-preview"]
    assert cleanup["needs"] == "scope"
    assert "needs.scope.outputs.render == 'false'" in cleanup["if"]
    # A scope that failed leaves render empty, which must not delete a preview.
    assert "needs.scope.outputs.render != 'true'" not in cleanup["if"]
    # The build/deploy path stays off for that PR, so nothing re-publishes it.
    assert "needs.scope.outputs.render == 'true'" in shared["jobs"]["build"]["if"]


def test_stable_browser_check_succeeds_without_rendering_unrelated_prs():
    check = load("example-preview")["jobs"]["check-preview"]
    assert check["name"] == "Example preview browser"
    assert "always()" in check["if"]
    assert "needs.docs.outputs.rendered" not in check["if"]
    assert check["steps"][0]["run"] == 'test "$RESULT" = success'
    gate = check["steps"][1]
    assert gate["id"] == "browser"
    assert "needs.docs.outputs.rendered == 'true'" in gate["env"]["RUN"]
    assert gate["env"]["RUN"] == "${{ needs.docs.outputs.rendered == 'true' }}"
    for step in check["steps"][2:]:
        assert step["if"] in (
            "steps.browser.outputs.run == 'true'",
            "steps.browser.outputs.run == 'true' && needs.docs.outputs.published == 'true'",
            "steps.browser.outputs.run == 'true' && needs.docs.outputs.published != 'true'",
            "steps.browser.outputs.run == 'true' && (github.event_name == 'pull_request' || inputs.preview-pr != '')",
        )


@pytest.mark.parametrize("has_preview", [False, True])
def test_cleanup_only_publishes_when_a_preview_exists(tmp_path, has_preview):
    def git(*args, cwd=None):
        return subprocess.check_output(
            ["git", *args], cwd=cwd or checkout, text=True, stderr=subprocess.PIPE
        )

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    remote = tmp_path / "remote.git"
    git("init", "--bare", str(remote))
    git("init", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    (checkout / "index.html").write_text("published main")
    git("add", "index.html")
    git("commit", "-m", "initial")
    git("remote", "add", "origin", str(remote))
    git("checkout", "-b", "gh-pages")
    if has_preview:
        preview = checkout / "pr-preview/pr-1"
        preview.mkdir(parents=True)
        (preview / "index.html").write_text("preview")
        git("add", "pr-preview/pr-1/index.html")
        git("commit", "-m", "preview")
    git("push", "origin", "main", "gh-pages")
    before = git("rev-parse", "gh-pages")
    git("checkout", "main")
    git("branch", "-D", "gh-pages")
    step = next(
        s
        for s in load("workspace-quarto-site")["jobs"]["cleanup-preview"]["steps"]
        if s.get("name") == "Remove PR preview"
    )
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=checkout,
        env=dict(os.environ, PR_NUMBER="1"),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    after = git("rev-parse", "refs/heads/gh-pages", cwd=remote)
    assert (before != after) == has_preview
    assert git("show", "gh-pages:index.html") == "published main"
    assert not git("ls-tree", "gh-pages", "pr-preview/pr-1")
    if not has_preview:
        assert "Preparing worktree" not in result.stderr


@pytest.mark.parametrize("has_comments", [False, True])
def test_cleanup_removes_only_bot_preview_comments(tmp_path, has_comments):
    comments = (
        [
            {
                "id": 11,
                "user": {"login": "github-actions[bot]"},
                "body": "📄 Preview: old",
            },
            {"id": 12, "user": {"login": "human"}, "body": "📄 Preview: keep"},
            {"id": 13, "user": {"login": "github-actions[bot]"}, "body": "Other check"},
        ]
        if has_comments
        else []
    )
    pages = (
        [
            comments,
            [
                {
                    "id": 14,
                    "user": {"login": "github-actions[bot]"},
                    "body": "📄 Preview: duplicate",
                }
            ],
        ]
        if has_comments
        else [[]]
    )
    (tmp_path / "comments.json").write_text(json.dumps(pages))
    fake = tmp_path / "gh"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys\n"
        "if 'DELETE' in sys.argv:\n"
        "    with open('deletions', 'a') as log: log.write(sys.argv[-1] + '\\n')\n"
        "else:\n"
        "    assert '--paginate' in sys.argv and '--slurp' in sys.argv\n"
        "    print(pathlib.Path('comments.json').read_text())\n"
    )
    fake.chmod(0o755)
    step = load("workspace-quarto-site")["jobs"]["cleanup-preview"]["steps"][-1]
    assert step["name"] == "Remove stale preview comment"
    result = subprocess.run(
        [sys.executable, "-c", step["run"]],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=dict(
            os.environ,
            PATH=f"{tmp_path}:{os.environ['PATH']}",
            GITHUB_REPOSITORY="owner/repo",
            PR_NUMBER="1",
        ),
    )
    assert result.returncode == 0, result.stderr
    log = tmp_path / "deletions"
    if has_comments:
        assert log.read_text().splitlines() == [
            "repos/owner/repo/issues/comments/11",
            "repos/owner/repo/issues/comments/14",
        ]
    else:
        assert not log.exists()


@pytest.mark.parametrize("failure", ["lookup", "decode", "record", "delete"])
def test_cleanup_fails_when_stale_comment_removal_cannot_be_verified(tmp_path, failure):
    fake = tmp_path / "gh"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "failure = os.environ['FAILURE']\n"
        "if 'DELETE' in sys.argv:\n"
        "    with open('deletions', 'a') as log: log.write(sys.argv[-1] + '\\n')\n"
        "    sys.exit(1 if failure == 'delete' else 0)\n"
        "if failure == 'lookup': sys.exit(1)\n"
        "if failure == 'decode': print('invalid JSON'); sys.exit(0)\n"
        "comment = {'user': {'login': 'github-actions[bot]'}, 'body': '📄 Preview: old'}\n"
        "if failure != 'record': comment['id'] = 11\n"
        "print(json.dumps([[comment], [dict(comment, id=14)]]))\n"
    )
    fake.chmod(0o755)
    step = load("workspace-quarto-site")["jobs"]["cleanup-preview"]["steps"][-1]
    result = subprocess.run(
        [sys.executable, "-c", step["run"]],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=dict(
            os.environ,
            PATH=f"{tmp_path}:{os.environ['PATH']}",
            GITHUB_REPOSITORY="owner/repo",
            PR_NUMBER="1",
            FAILURE=failure,
        ),
    )
    assert result.returncode != 0
    assert "::error::Could not remove the stale preview comment" in result.stdout
    log = tmp_path / "deletions"
    if failure == "delete":
        # Stop on the first failed deletion instead of reporting success or
        # continuing through later pages. A rerun can safely retry the cleanup.
        assert log.read_text().splitlines() == ["repos/owner/repo/issues/comments/11"]
    else:
        assert not log.exists()


def test_example_publishes_one_patch_through_existing_artifact_hook():
    site = load("example-preview")
    assert "make workspace-demo" in site["jobs"]["docs"]["with"]["artifact-command"]
    assert (
        "example-demo-pr"
        not in (ROOT / ".github/workflows/example-preview.yml").read_text()
    )
    assert "demo-pr" not in load("docker")["jobs"]
    for name in ("README.md", "examples/workspace/README.md", "DEVELOPER.md"):
        text = (ROOT / name).read_text()
        assert "pull/281" not in text and "pr-preview/pr-281" not in text
        assert "https://allenai.github.io/asta-plugins/demo/" in text


def test_example_uses_current_scaffold_and_managed_inputs():
    script = (ROOT / "scripts/check-workspace-local.sh").read_text()
    assert 'state["source_ref"] == os.environ["GITHUB_SHA"]' in script
    assert "for extension in asta-theme evidence asta-slides" in script
    assert "diff -r" in script
    assert "make workspace-assets workspace-viewers workspace-check-gate" in script
    assert "make check\n" not in script
    assert "make preview-artifact-check" not in script


def test_published_demo_reuses_local_content_assertions():
    make = (ROOT / "Makefile").read_text()
    assert 'local-what-changed-demo.py --site "$(PREVIEW_SITE)/demo"' in make


def test_demo_what_changed_is_built_once_by_the_site_workflow():
    assert (
        "build-workspace-demo.py"
        not in (ROOT / "scripts/check-workspace-local.sh").read_text()
    )
    assert (
        "make workspace-demo"
        in load("example-preview")["jobs"]["docs"]["with"]["artifact-command"]
    )


def test_all_example_browser_checks_use_the_installed_browser_path():
    tools = load("example-workspace")["jobs"]["tools"]
    assert tools["env"]["PLAYWRIGHT_BROWSERS_PATH"] == "/tmp/asta-test-chromium"
    assert (
        "playwright install --with-deps chromium"
        in (ROOT / "scripts/check-workspace-local.sh").read_text()
    )


def test_pr_uses_x86_and_release_or_manual_adds_arm():
    workflow = load("example-workspace")
    assert "push" not in workflow["on"]
    for job in ("python", "tools", "comparison"):
        assert (
            "github.event_name == 'pull_request'"
            in workflow["jobs"][job]["strategy"]["matrix"]["runner"]
        )
    assert (
        load("example-preview")["jobs"]["docs-arm"]["if"]
        == "github.event_name == 'workflow_dispatch' || inputs.release-check"
    )


def test_edit_comparison_runs_independently_on_workspace_prs():
    jobs = load("example-workspace")["jobs"]
    assert jobs["comparison"]["needs"] == "scope"
    assert len(jobs["comparison"]["strategy"]["matrix"]["case"]) == 13
    assert "tools" not in jobs["comparison"]["needs"]


def test_one_browser_job_checks_the_built_preview():
    job = load("example-preview")["jobs"]["check-preview"]
    assert job["needs"] == "docs"
    assert any(step.get("run") == "make workspace-browser" for step in job["steps"])
    make = (ROOT / "Makefile").read_text()
    for script in (
        "workspace-slides.mjs",
        "deck-review.py",
        "example-preview.mjs",
        "local-what-changed-demo.py",
    ):
        assert script in make


@pytest.mark.parametrize(
    "invalid", [None, "closed", "fork", "deleted", "ref", "sha", "event", "number"]
)
def test_dispatched_preview_requires_exact_open_same_repo_head(tmp_path, invalid):
    pr = {
        "state": "closed" if invalid == "closed" else "open",
        "head": {
            "repo": None
            if invalid == "deleted"
            else {"full_name": "fork/repo" if invalid == "fork" else "owner/repo"},
            "ref": "example-demo-pr",
            "sha": "a" * 40,
        },
        "base": {"sha": "b" * 40},
    }
    fake = tmp_path / "gh"
    fake.write_text(f"#!{sys.executable}\nimport json\nprint({json.dumps(pr)!r})\n")
    fake.chmod(0o755)
    output = tmp_path / "out"
    script = load("workspace-quarto-site")["jobs"]["scope"]["steps"][0]["run"]
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=dict(
            os.environ,
            PATH=f"{tmp_path}:{os.environ['PATH']}",
            EVENT="push" if invalid == "event" else "workflow_dispatch",
            ACTION="",
            DISPATCH_PR="not-a-number" if invalid == "number" else "281",
            SITE_DIR="examples/workspace",
            GITHUB_REPOSITORY="owner/repo",
            GITHUB_REF="refs/heads/other"
            if invalid == "ref"
            else "refs/heads/example-demo-pr",
            GITHUB_SHA="c" * 40 if invalid == "sha" else "a" * 40,
            GITHUB_OUTPUT=str(output),
        ),
    )
    if invalid:
        assert result.returncode != 0
        assert not output.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert output.read_text() == f"base-sha={'b' * 40}\nrender=true\n"


@pytest.mark.parametrize(
    "path,runs",
    [
        ("src/asta/commands/workspace.py", True),
        ("examples/workspace/a\nline.qmd", True),
        ("src/asta/commands/workspace_selection.py", True),
        ("src/asta/commands/workspace_versions.py", True),
        ("src/asta/commands/workspace_comparison.py", True),
        ("plugins/asta-tools/skills/workspace/assets/what-changed.py", True),
        ("examples/workspace/index.qmd", True),
        ("README.md", True),
        ("DEVELOPER.md", True),
        ("docs/overleaf-sync.md", True),
        ("Dockerfile", True),
        ("image/skills-cli/package.json", True),
        ("src/asta/__init__.py", True),
        ("plugins/asta-tools/skills/find-literature/SKILL.md", False),
        (".github/workflows/example-workspace.yml", True),
        ("tests/browser/workspace-differential.py", True),
        ("tests/browser/report_signature.py", True),
        ("tests/browser/example-preview.mjs", True),
        (".github/workflows/ci.yml", True),
    ],
)
def test_edit_comparison_gate_uses_the_pr_diff(tmp_path, path, runs):
    def git(*args):
        return subprocess.check_output(
            [
                "git",
                "-c",
                "user.name=test",
                "-c",
                "user.email=test@example.invalid",
                *args,
            ],
            cwd=tmp_path,
            text=True,
            stderr=subprocess.PIPE,
        ).strip()

    git("init", "-b", "main")
    git("commit", "--allow-empty", "-qm", "base")
    base = git("rev-parse", "HEAD")
    changed = tmp_path / path
    changed.parent.mkdir(parents=True, exist_ok=True)
    changed.write_text("a change\n")
    git("add", path)
    git("commit", "-qm", "head")
    project = tmp_path / "examples/workspace"
    project.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/workspace-scope.py"), base],
        env=dict(
            os.environ,
            WORKSPACE_PATHS=(ROOT / "Makefile")
            .read_text()
            .split("WORKSPACE_PATHS := ", 1)[1]
            .splitlines()[0],
        ),
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(runs).lower()


def test_unpublished_prs_check_the_same_build_without_write_access():
    shared = load("workspace-quarto-site")
    assert (
        shared["on"]["workflow_call"]["outputs"]["published"]["value"]
        == "${{ jobs.deploy.result == 'success' }}"
    )
    browser = load("example-preview")["jobs"]["check-preview"]
    assert browser["permissions"] == {"contents": "read"}
    download = next(
        s
        for s in browser["steps"]
        if s.get("uses", "").startswith("actions/download-artifact@")
    )
    assert "needs.docs.outputs.published != 'true'" in download["if"]
    assert download["with"]["name"] == "site-ubuntu-latest"
    upload = next(
        s
        for s in shared["jobs"]["build"]["steps"]
        if s.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert upload["with"]["name"] == "site-${{ inputs.build-runner }}"
    assert (
        shared["on"]["workflow_call"]["inputs"]["build-runner"]["default"]
        == "ubuntu-latest"
    )
    assert download["with"]["path"].startswith("preview-site/pr-preview/pr-")


def test_workspace_test_matrix_selects_its_interpreter():
    job = load("example-workspace")["jobs"]["python"]
    assert job["env"]["UV_PYTHON"] == "${{ matrix.python }}"
    import re

    assert not re.search(
        r"test_.*\.py|--ignore", (ROOT / ".github/workflows/ci.yml").read_text()
    )


@pytest.mark.parametrize("workflow", ["example-workspace", "example-preview"])
@pytest.mark.parametrize(
    "value,exit_code", [("true", 0), ("false", 0), ("", 0), ("oops", 0), ("false", 1)]
)
def test_workspace_scope_step_rejects_errors_and_invalid_outputs(
    tmp_path, workflow, value, exit_code
):
    step = load(workflow)["jobs"]["scope"]["steps"][-1]
    fake = tmp_path / "make"
    fake.write_text(f"#!/bin/sh\nprintf '%s\\n' '{value}'\nexit {exit_code}\n")
    fake.chmod(0o755)
    output = tmp_path / "out"
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step["run"]],
        env=dict(
            os.environ,
            PATH=f"{tmp_path}:{os.environ['PATH']}",
            GITHUB_OUTPUT=str(output),
        ),
        capture_output=True,
        text=True,
    )
    valid = exit_code == 0 and value in ("true", "false")
    assert (result.returncode == 0) == valid
    assert output.exists() == valid
    if valid:
        assert output.read_text() == f"workspace={value}\n"


def test_example_passes_one_scope_to_shared_build_and_cleanup():
    docs = load("example-preview")["jobs"]["docs"]
    assert "if" not in docs
    assert docs["with"]["render"] == "${{ needs.scope.outputs.workspace }}"
    assert "render-paths" not in docs["with"]


@pytest.mark.parametrize(
    "scope,expected", [("true", "true"), ("false", "false"), ("bad", None)]
)
def test_shared_scope_honors_caller_without_file_lookup(
    tmp_path, monkeypatch, scope, expected
):
    monkeypatch.setenv("RENDER", scope)
    # The fake gh rejects this response type if called; caller scope needs no API.
    result, output = _run_shared_scope(tmp_path, [])
    if expected is None:
        assert result.returncode != 0
        assert not output.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert output.read_text() == f"render={expected}\n"


@pytest.mark.parametrize(
    "shard,count,expected", [(0, 1, 0), (1, 2, 0), (2, 2, 1), (0, 0, 1)]
)
def test_empty_workspace_shard_never_falls_back_to_all_tests(
    tmp_path, shard, count, expected
):
    (tmp_path / "tests/workspace").mkdir(parents=True)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/test-workspace.py"),
            "tests/workspace",
            "tests/workspace/tools",
            str(shard),
            str(count),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) == (expected == 0)
    assert "pytest" not in result.stdout


def test_release_reuses_all_checks_on_both_architectures():
    release = load("workspace-release-checks")["jobs"]
    plugins = release["plugins"]
    assert plugins["uses"] == "./.github/workflows/ci.yml"
    assert plugins["strategy"]["matrix"]["runner"] == [
        "ubuntu-latest",
        "ubuntu-24.04-arm",
    ]
    assert (
        release["devcontainer"]["uses"] == "./.github/workflows/devcontainer-smoke.yml"
    )
    assert load("example-workspace")["jobs"]["dom"]["strategy"]["matrix"]["runner"]
    arm = load("example-preview")["jobs"]["docs-arm"]
    assert (
        'make -C "$GITHUB_WORKSPACE" workspace-browser'
        in arm["with"]["artifact-command"]
    )


def test_workspace_partition_includes_nested_tests_and_excludes_tools(
    tmp_path, monkeypatch
):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "workspace_shard", ROOT / "scripts/test-workspace.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    for name in (
        "tests/workspace/test_a.py",
        "tests/workspace/nested/test_b.py",
        "tests/workspace/tools/test_real.py",
        "tests/test_other.py",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(runner.subprocess, "call", lambda args: calls.append(args) or 0)
    selected = []
    for shard in range(3):
        monkeypatch.setattr(
            sys,
            "argv",
            ["runner", "tests/workspace", "tests/workspace/tools", str(shard), "3"],
        )
        try:
            runner.main()
        except SystemExit as exc:
            assert exc.code == 0
    for call in calls:
        selected.extend(call[4:])
    assert sorted(selected) == [
        "tests/workspace/nested/test_b.py",
        "tests/workspace/test_a.py",
    ]
