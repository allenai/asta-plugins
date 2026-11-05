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


def _run_shared_scope(tmp_path, files):
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
    result = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True
    )
    return result, output


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
    for step in check["steps"][1:]:
        assert "needs.docs.outputs.rendered == 'true'" in step["if"]


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
