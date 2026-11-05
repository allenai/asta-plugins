"""The example dogfoods workspace publication; releases only validate."""

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
    "paths,expected",
    [
        (["examples/workspace/slides/attention/slides.qmd"], "true"),
        (["plugins/asta-tools/skills/workspace/SKILL.md"], "false"),
        (["elsewhere.qmd", "examples/workspace/old.qmd"], "true"),
        (["plugins/asta-tools/skills/workspace/assets/asta-slides/theme.scss"], "true"),
    ],
)
def test_shared_scope_matches_current_and_previous_paths(tmp_path, paths, expected):
    workflow = load("workspace-quarto-site")
    script = workflow["jobs"]["scope"]["steps"][0]["run"]
    fake = tmp_path / "gh"
    fake.write_text(f"#!{sys.executable}\nprint({chr(10).join(paths)!r})\n")
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
    subprocess.run([sys.executable, "-c", script], env=env, check=True)
    assert output.read_text() == f"render={expected}\n"
    assert ".previous_filename // empty" in script


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
    assert "needs" not in shared["jobs"]["cleanup-preview"]
    assert "scope.outputs.render" not in shared["jobs"]["cleanup-preview"]["if"]
    assert "closed" in shared["jobs"]["cleanup-preview"]["if"]


def test_stable_browser_check_succeeds_without_rendering_unrelated_prs():
    check = load("example-preview")["jobs"]["check-preview"]
    assert check["name"] == "Example preview browser"
    assert "always()" in check["if"]
    assert "needs.docs.outputs.rendered" not in check["if"]
    assert check["steps"][0]["run"] == 'test "$RESULT" = success'
    for step in check["steps"][1:]:
        assert "needs.docs.outputs.rendered == 'true'" in step["if"]
