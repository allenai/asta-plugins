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
    assert set(release["jobs"]) == {"build", "theme"}
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
    assert "head.repo.full_name == github.repository" in gate["env"]["RUN"]
    assert "github.actor != 'dependabot[bot]'" in gate["env"]["RUN"]
    for step in check["steps"][2:]:
        assert step["if"] == "steps.browser.outputs.run == 'true'"


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


def test_example_has_no_demo_copy_and_links_a_real_pr_preview():
    example = ROOT / "examples/workspace"
    for name in ("build-demo.py", "refresh-demo.py", "demo-edits.patch"):
        assert not (example / "scripts" / name).exists()
    assert "demo" not in (example / "Makefile").read_text()
    assert "artifact-command" not in load("example-preview")["jobs"]["docs"]["with"]
    build = load("example-workspace")["jobs"]["build"]
    assert not any("upload-pages-artifact" in s.get("uses", "") for s in build["steps"])
    for readme in (ROOT / "README.md", example / "README.md"):
        text = readme.read_text()
        assert "asta-plugins/demo/" not in text
        assert "https://allenai.github.io/asta-plugins/pr-preview/pr-" in text
