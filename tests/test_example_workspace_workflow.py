"""The example dogfoods workspace publication; releases only validate."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


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
        ([{"filename": "plugins/asta-tools/skills/workspace/SKILL.md"}], "false"),
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
        RENDER_PATHS=load("example-preview")["jobs"]["docs"]["with"]["render-paths"],
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
    result, output = _run_shared_scope(tmp_path, files)
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
    caller = load("example-preview")
    assert caller["on"]["push"]["branches"] == ["main"]
    assert "closed" in caller["on"]["pull_request"]["types"]
    assert "paths" not in caller["on"]["pull_request"]
    assert (
        caller["jobs"]["docs"]["uses"]
        == "./.github/workflows/workspace-quarto-site.yml"
    )
    release = load("example-workspace")
    assert set(release["jobs"]) == {"build"}
    assert not (ROOT / "scripts/request-example-pages-build.sh").exists()
    shared = load("workspace-quarto-site")
    cleanup = shared["jobs"]["cleanup-preview"]
    # Closing always cleans up, even if scoping failed or found nothing.
    assert cleanup["if"].startswith("always()")
    assert "github.event.action == 'closed' ||" in cleanup["if"]


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
    example = ROOT / "examples/workspace"
    for name in ("build-demo.py", "refresh-demo.py", "demo-edits.patch"):
        assert not (example / "scripts" / name).exists()
    assert "demo" not in (example / "Makefile").read_text()
    jobs = load("example-preview")["jobs"]
    command = jobs["docs"]["with"]["artifact-command"]
    assert command == jobs["docs-arm"]["with"]["artifact-command"]
    assert "uv tool install --force ." in command
    assert "build-workspace-demo.py examples/workspace/_site/demo" in command
    assert "latest-tex" in command
    assert (ROOT / "examples/workspace-demo.patch").is_file()
    build = load("example-workspace")["jobs"]["build"]
    assert not any("upload-pages-artifact" in s.get("uses", "") for s in build["steps"])
    for readme in (ROOT / "README.md", example / "README.md"):
        text = readme.read_text()
        assert "https://allenai.github.io/asta-plugins/pr-preview/pr-" in text


def test_example_uses_current_scaffold_and_managed_inputs():
    example = ROOT / "examples/workspace"
    assets = ROOT / "plugins/asta-tools/skills/workspace/assets"
    assert (
        (example / "Makefile")
        .read_text()
        .startswith((assets / "Makefile.managed").read_text())
    )
    assert not (example / "workspace.mk").exists()
    for path in ("_extensions/asta-theme/light.scss", ".asta/cache/workspace.mk"):
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", path],
            cwd=example,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
    source = yaml.load(
        (example / ".github/workflows/docs.yml").read_text(), Loader=yaml.BaseLoader
    )
    assert source["jobs"]["docs"]["uses"].startswith(
        "allenai/asta-plugins/.github/workflows/workspace-quarto-site.yml@"
    )
    build = load("example-workspace")["jobs"]["build"]
    step = next(
        s for s in build["steps"] if s.get("name") == "Build and validate the example"
    )
    assert build["env"]["ASTA_WORKSPACE_RESOLVED_SHA"] == "${{ github.sha }}"
    assert step["run"].index("uv tool install") < step["run"].index("make check")
    assert 'state["source_ref"] == os.environ["GITHUB_SHA"]' in step["run"]
    assert "for extension in asta-theme evidence asta-slides" in step["run"]
    assert "diff -r" in step["run"]


def test_published_demo_reuses_local_content_assertions():
    steps = load("example-preview")["jobs"]["check-preview"]["steps"]
    by_name = {s.get("name"): s for s in steps}
    demo = by_name["Check the demo What changed in the published preview"]
    assert "local-what-changed-demo.py --site" in demo["run"]
    assert "preview-site/pr-preview/pr-$PR_NUMBER" in demo["run"]
    assert (
        'if [ "$HEAD_BRANCH" != example-demo-pr ]; then site="$site/demo"; fi'
        in demo["run"]
    )
    command = load("example-preview")["jobs"]["docs"]["with"]["artifact-command"]
    assert (
        '[ "${GITHUB_HEAD_REF:-$GITHUB_REF_NAME}" != example-demo-pr ] || exit 0'
        in command
    )


def test_demo_what_changed_is_built_once_by_the_site_workflow():
    local = yaml.dump(load("example-workspace"))
    for built_elsewhere in (
        "build-workspace-demo.py",
        "workspace-preview-path.py",
        "local-what-changed-demo.py",
        "render-slides.py",
    ):
        assert built_elsewhere not in local
    command = load("example-preview")["jobs"]["docs"]["with"]["artifact-command"]
    assert "build-workspace-demo.py" in command


def test_all_example_browser_checks_use_the_installed_browser_path():
    build = load("example-workspace")["jobs"]["build"]
    assert build["env"]["PLAYWRIGHT_BROWSERS_PATH"] == "/tmp/asta-test-chromium"
    browser_steps = [s for s in build["steps"] if "playwright==" in s.get("run", "")]
    install = next(
        i for i, s in enumerate(browser_steps) if "playwright install" in s["run"]
    )
    assert install == 0
    assert browser_steps
    assert all(
        "export PLAYWRIGHT_BROWSERS_PATH=" not in s["run"] for s in browser_steps
    )


def test_pr_waits_on_x86_only_and_main_adds_arm():
    example = load("example-workspace")
    runners = example["jobs"]["build"]["strategy"]["matrix"]["runner"]
    assert '["ubuntu-latest"]' in runners
    assert '"ubuntu-24.04-arm"' in runners
    assert "github.event_name == 'pull_request'" in runners
    assert example["on"]["push"]["branches"] == ["main"]
    site = load("example-preview")["jobs"]
    assert "github.event_name != 'pull_request'" in site["docs-arm"]["if"]
    assert "needs" not in site["docs-arm"]
    assert site["docs-arm"]["with"]["publish"] == "false"
    assert site["check-preview"]["needs"] == "docs"


def test_edit_comparison_runs_on_main_and_on_what_changed_prs():
    steps = load("example-workspace")["jobs"]["build"]["steps"]
    checkout = next(
        s for s in steps if s.get("uses", "").startswith("actions/checkout@")
    )
    # The PR base used by the gate must exist on real CI checkouts too.
    assert checkout["with"]["fetch-depth"] == "0"
    by_name = {s.get("name"): s for s in steps}
    gate = by_name["Decide whether the edit comparison runs"]
    for path in (
        "src/asta/commands/workspace*.py",
        "plugins/asta-tools/skills/workspace/assets",
        "examples/workspace",
    ):
        assert path in gate["run"]
    compare = by_name["Compare selected edits with same-run full reports"]
    assert compare["if"] == "steps.differential.outputs.run == 'true'"


def test_one_browser_job_checks_the_built_preview():
    steps = load("example-preview")["jobs"]["check-preview"]["steps"]
    runs = "\n".join(s.get("run", "") for s in steps)
    for check in (
        "workspace-slides.mjs",
        "deck-review.py",
        "npm test --",
        "example-preview.mjs",
        "local-what-changed-demo.py",
    ):
        assert check in runs
    assert "examples/workspace/_site" not in runs


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
        ("src/asta/commands/workspace_selection.py", True),
        ("src/asta/commands/workspace_versions.py", True),
        ("src/asta/commands/workspace_comparison.py", True),
        ("plugins/asta-tools/skills/workspace/assets/what-changed.py", True),
        ("examples/workspace/index.qmd", True),
        ("README.md", False),
        (".github/workflows/example-workspace.yml", True),
        ("tests/browser/workspace-differential.py", True),
        ("tests/browser/report_signature.py", True),
        ("tests/browser/example-preview.mjs", False),
        (".github/workflows/ci.yml", False),
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
    steps = load("example-workspace")["jobs"]["build"]["steps"]
    script = next(s["run"] for s in steps if s.get("id") == "differential")
    result = subprocess.run(
        ["bash", "-c", script.replace("${{ github.event_name }}", "pull_request")],
        cwd=project,
        capture_output=True,
        text=True,
        env=dict(
            os.environ,
            BASE_SHA=base,
            GITHUB_OUTPUT=str(tmp_path / "out"),
            GITHUB_STEP_SUMMARY=str(tmp_path / "summary"),
        ),
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "out").read_text() == f"run={str(runs).lower()}\n"


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
    job = load("ci")["jobs"]["workspace-test"]
    assert job["env"]["UV_PYTHON"] == "${{ matrix.python-version }}"
