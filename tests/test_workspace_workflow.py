import os
import re
import shutil
import subprocess
import tarfile
import tomllib
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(".github/workflows/workspace-quarto-site.yml")
WORKSPACE_ASSETS = Path("plugins/asta-tools/skills/workspace/assets")


def _run_paper_step(tmp_path: Path, *, download_fails: bool = False):
    workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    step = next(
        item for item in workflow["jobs"]["build"]["steps"] if item.get("id") == "paper"
    )
    script = step["run"].replace("${{ job.workflow_repository }}", "owner/repo")
    script = script.replace("${{ job.workflow_sha }}", "source-commit")
    source = WORKSPACE_ASSETS / "paper-discovery.py"
    project = tmp_path / "project"
    paper = project / "paper"
    paper.mkdir(parents=True)
    (paper / "main.tex").write_text("paper")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(
        "#!/bin/sh\n"
        '[ "${FAIL_CURL:-0}" != 1 ] || exit 1\n'
        'while [ "$#" -gt 0 ] && [ "$1" != -o ]; do shift; done\n'
        '[ "$#" -ge 2 ] || exit 2\n'
        'cp "$DISCOVERY_SOURCE" "$2"\n'
    )
    curl.chmod(0o755)
    sudo = bin_dir / "sudo"
    sudo.write_text("#!/bin/sh\nexit 1\n")
    sudo.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "PR_BASE": "",
        "DISCOVERY_SOURCE": str(source.resolve()),
        "FAIL_CURL": "1" if download_fails else "0",
    }
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", script],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
    )
    return project, result


def test_paper_toolchain_failure_keeps_preview_diagnostic(tmp_path: Path) -> None:
    project, result = _run_paper_step(tmp_path)

    assert result.returncode != 0
    assert (
        project / "_site/paper-previews/paper/build-failed.txt"
    ).read_text().strip() == ("Could not update LaTeX package lists.")
    assert (
        project / "_site/paper-previews/paper/preview.json"
    ).read_text().strip() == ('{"changed":false}')


def test_paper_discovery_failure_keeps_site_diagnostic(tmp_path: Path) -> None:
    project, result = _run_paper_step(tmp_path, download_fails=True)

    assert result.returncode != 0
    assert (project / "_site/paper-previews/build-failed.txt").read_text().strip() == (
        "Could not download the paper discovery script."
    )


def test_what_changed_project_override_runs_before_write_enabled_deploy(
    tmp_path: Path,
) -> None:
    workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    build = workflow["jobs"]["build"]
    deploy = workflow["jobs"]["deploy"]
    assert build["permissions"]["contents"] == "read"
    assert deploy["permissions"]["contents"] == "write"
    step = next(s for s in build["steps"] if s.get("name") == "Generate What changed")
    assert not any("what-changed.py" in s.get("run", "") for s in deploy["steps"])

    remote = tmp_path / "remote.git"
    project = tmp_path / "project"
    subprocess.run(
        ["git", "init", "--bare", str(remote)], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "init", "-b", "gh-pages", str(project)], check=True, capture_output=True
    )

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)

    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    (project / "index.html").write_text("deployed main")
    git("add", "index.html")
    git("commit", "-m", "Baseline")
    git("remote", "add", "origin", str(remote))
    git("push", "origin", "gh-pages")
    git("switch", "-c", "main")
    (project / "scripts").mkdir()
    (project / "scripts/what-changed.py").write_text(
        "import argparse\n"
        "from pathlib import Path\n"
        "p = argparse.ArgumentParser()\n"
        "for arg in ('old', 'new', 'out', 'title'):\n"
        "    p.add_argument('--' + arg)\n"
        "a = p.parse_args()\n"
        "Path(a.out).write_text('custom: ' + Path(a.old, 'index.html').read_text() + '\\n' + a.title)\n"
    )
    git("add", "scripts/what-changed.py")
    git("commit", "-m", "Customize diff")
    git("update-ref", "refs/remotes/origin/gh-pages", "HEAD")
    (project / "_site").mkdir()
    (project / "_site/index.html").write_text("PR content")

    script = step["run"].replace("${{ job.workflow_repository }}", "owner/repo")
    script = script.replace("${{ job.workflow_sha }}", "source-commit")
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", script],
        cwd=project,
        env={**os.environ, "PR_NUMBER": "7"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    page = (project / "_site/what-changed.html").read_text()
    assert page.startswith("custom: deployed main\nPR #7 · Pages ")
    assert re.search(r"Pages [0-9a-f]{12}$", page)
    assert "Using project-owned" in result.stdout

    (project / "_site/what-changed.html").unlink()
    (project / "scripts/what-changed.py").write_text(
        "import argparse\n"
        "from pathlib import Path\n"
        "p = argparse.ArgumentParser()\n"
        "for arg in ('old', 'new', 'out', 'title'):\n"
        "    p.add_argument('--' + arg)\n"
        "a = p.parse_args()\n"
        "Path(a.out).write_text('partial')\n"
        "raise RuntimeError('failed after writing')\n"
    )
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", script],
        cwd=project,
        env={**os.environ, "PR_NUMBER": "7"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not (project / "_site/what-changed.html").exists()
    assert "what-changed page generation failed" in result.stdout


def test_what_changed_uses_managed_generator_without_project_copy(
    tmp_path: Path,
) -> None:
    workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    step = next(
        s
        for s in workflow["jobs"]["build"]["steps"]
        if s.get("name") == "Generate What changed"
    )
    project = tmp_path / "project"
    (project / "_site").mkdir(parents=True)
    (project / "_site/index.html").write_text(
        "<html><head><title>Test</title></head><body><main>New page</main></body></html>"
    )
    subprocess.run(
        ["git", "init", "-b", "main", str(project)], check=True, capture_output=True
    )
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(remote)], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote)],
        cwd=project,
        check=True,
        capture_output=True,
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(
        "#!/bin/sh\n"
        'while [ "$#" -gt 0 ] && [ "$1" != -o ]; do shift; done\n'
        '[ "$#" -ge 2 ] || exit 2\n'
        'cp "$MANAGED_SOURCE" "$2"\n'
    )
    curl.chmod(0o755)
    script = step["run"].replace("${{ job.workflow_repository }}", "owner/repo")
    script = script.replace("${{ job.workflow_sha }}", "source-commit")
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", script],
        cwd=project,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "MANAGED_SOURCE": str((WORKSPACE_ASSETS / "what-changed.py").resolve()),
            "PR_NUMBER": "8",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (project / "_site/what-changed.html").is_file()
    assert "no deployed baseline" in (project / "_site/what-changed.html").read_text()


@pytest.mark.parametrize("failed_command", ["ls-remote", "fetch", "archive"])
def test_what_changed_skips_diff_when_baseline_read_fails(
    tmp_path: Path, failed_command: str
) -> None:
    workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    step = next(
        s
        for s in workflow["jobs"]["build"]["steps"]
        if s.get("name") == "Generate What changed"
    )
    project = tmp_path / "project"
    (project / "_site").mkdir(parents=True)
    (project / "_site/index.html").write_text("PR content")
    subprocess.run(
        ["git", "init", "-b", "main", str(project)], check=True, capture_output=True
    )
    remote = tmp_path / "remote.git"
    baseline = tmp_path / "baseline"
    subprocess.run(
        ["git", "init", "--bare", str(remote)], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "init", "-b", "gh-pages", str(baseline)],
        check=True,
        capture_output=True,
    )
    (baseline / "index.html").write_text("deployed main")
    for args in (
        ("config", "user.name", "Test"),
        ("config", "user.email", "test@example.invalid"),
        ("add", "index.html"),
        ("commit", "-m", "Baseline"),
        ("remote", "add", "origin", str(remote)),
        ("push", "origin", "gh-pages"),
    ):
        subprocess.run(["git", *args], cwd=baseline, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote)],
        cwd=project,
        check=True,
        capture_output=True,
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    git = bin_dir / "git"
    git.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$1" >> "$GIT_COMMAND_LOG"\n'
        '[ "$1" != "$FAILED_COMMAND" ] || exit 1\n'
        'exec "$REAL_GIT" "$@"\n'
    )
    git.chmod(0o755)
    script = step["run"].replace("${{ job.workflow_repository }}", "owner/repo")
    script = script.replace("${{ job.workflow_sha }}", "source-commit")
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", script],
        cwd=project,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REAL_GIT": shutil.which("git"),
            "FAILED_COMMAND": failed_command,
            "GIT_COMMAND_LOG": str(tmp_path / "git-commands.log"),
            "PR_NUMBER": "8",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not (project / "_site/what-changed.html").exists()
    assert "skipping the diff page" in result.stdout
    commands = (tmp_path / "git-commands.log").read_text().splitlines()
    assert failed_command in commands
    if failed_command == "archive":
        assert "fetch" in commands


def test_workspace_can_pin_quarto_for_generated_sources() -> None:
    workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    assert workflow["on"]["workflow_call"]["inputs"]["quarto-version"]["default"] == (
        "release"
    )
    setup = next(
        step
        for step in workflow["jobs"]["build"]["steps"]
        if step.get("uses") == "quarto-dev/quarto-actions/setup@v2"
    )
    assert setup["with"]["version"] == "${{ inputs.quarto-version }}"


def test_workspace_assets_use_called_workflow_identity() -> None:
    workflow = WORKFLOW.read_text()

    assert workflow.count("${{ job.workflow_repository }}") == 4
    assert workflow.count("${{ job.workflow_sha }}") == 4
    assert "github.job_workflow" not in workflow


def test_workspace_deploy_commit_identifies_its_workflow_run() -> None:
    workflow = WORKFLOW.read_text()

    assert "git commit --allow-empty" in workflow
    assert (
        "Deploy ${{ github.event_name }} ${{ github.sha }} (run ${{ github.run_id }})"
        in workflow
    )
    assert "for asset in quarto-check.sh wait-for-preview.sh" in workflow


def test_workspace_checks_both_vendored_scripts_for_drift() -> None:
    workflow = WORKFLOW.read_text()

    assert "for asset in quarto-check.sh wait-for-preview.sh" in workflow


def test_scaffolded_workflow_ref_matches_project_version() -> None:
    """Release-managed workspace assets must advance under one version tag."""
    project_version = tomllib.loads(Path("pyproject.toml").read_text())["project"][
        "version"
    ]
    scaffold = (WORKSPACE_ASSETS / "docs.yml").read_text()
    match = re.search(r"workspace-quarto-site\.yml@v([0-9.]+)", scaffold)

    assert match is not None
    assert match.group(1) == project_version


@pytest.mark.parametrize("quote", ["", "'", '"'])
def test_workspace_makefile_fetches_managed_targets(tmp_path: Path, quote: str) -> None:
    archive_root = tmp_path / "archive" / "asta-plugins-test"
    source = archive_root / WORKSPACE_ASSETS / "workspace.mk"
    source.parent.mkdir(parents=True)
    source.write_text("managed:\n\t@echo managed-target\n")
    archive = tmp_path / "asta-plugins.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(archive_root, arcname=archive_root.name)

    project = tmp_path / "project"
    (project / ".github/workflows").mkdir(parents=True)
    (project / ".github/workflows/docs.yml").write_text(
        f"uses: {quote}allenai/asta-plugins/.github/workflows/"
        f"workspace-quarto-site.yml@v1.2.3{quote}\n"
    )
    (project / "Makefile").write_text((WORKSPACE_ASSETS / "Makefile").read_text())
    with (project / "Makefile").open("a") as file:
        file.write("\nproject: managed\n\t@echo project-target\n")
    result = subprocess.run(
        ["make", "project"],
        cwd=project,
        env={"ASTA_PLUGINS_ARCHIVE_URL": archive.as_uri(), "PATH": os.environ["PATH"]},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert "managed-target" in result.stdout
    assert "project-target" in result.stdout
    assert (project / ".asta/cache/v1.2.3/workspace.mk").read_text() == (
        source.read_text()
    )


def test_workspace_makefile_refreshes_floating_ref_and_uses_offline_cache(
    tmp_path: Path,
) -> None:
    source = tmp_path / "archive/asta-plugins-test" / WORKSPACE_ASSETS / "workspace.mk"
    source.parent.mkdir(parents=True)
    archive = tmp_path / "asta-plugins.tar.gz"

    def write_archive(value: str) -> None:
        source.write_text(f"managed:\n\t@echo {value}\n")
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(source.parents[5], arcname="asta-plugins-test")

    project = tmp_path / "project"
    (project / ".github/workflows").mkdir(parents=True)
    (project / ".github/workflows/docs.yml").write_text(
        "uses: allenai/asta-plugins/.github/workflows/workspace-quarto-site.yml@main\n"
    )
    (project / "Makefile").write_text((WORKSPACE_ASSETS / "Makefile").read_text())
    env = {"ASTA_PLUGINS_ARCHIVE_URL": archive.as_uri(), "PATH": os.environ["PATH"]}

    write_archive("first")
    first = subprocess.run(
        ["make", "managed"], cwd=project, env=env, capture_output=True, text=True
    )
    assert first.returncode == 0, first.stderr
    assert "first" in first.stdout

    cache = project / ".asta/cache/main/workspace.mk"
    os.utime(cache, (0, 0))
    write_archive("second")
    second = subprocess.run(
        ["make", "managed"], cwd=project, env=env, capture_output=True, text=True
    )
    assert second.returncode == 0, second.stderr
    assert "second" in second.stdout

    os.utime(cache, (0, 0))
    offline = subprocess.run(
        ["make", "managed"],
        cwd=project,
        env={
            "ASTA_PLUGINS_ARCHIVE_URL": (tmp_path / "missing.tar.gz").as_uri(),
            "PATH": os.environ["PATH"],
        },
        capture_output=True,
        text=True,
    )
    assert offline.returncode == 0, offline.stderr
    assert "second" in offline.stdout
    assert "using cached Makefile" in offline.stderr


def test_workspace_makefile_prefers_committed_override(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "Makefile").write_text((WORKSPACE_ASSETS / "Makefile").read_text())
    (project / "workspace.mk").write_text("managed:\n\t@echo custom-target\n")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "add", "workspace.mk"], cwd=project, check=True)
    result = subprocess.run(
        ["make", "managed"],
        cwd=project,
        env={
            "ASTA_PLUGINS_ARCHIVE_URL": (tmp_path / "missing.tar.gz").as_uri(),
            "PATH": os.environ["PATH"],
        },
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert "custom-target" in result.stdout
    assert not (project / ".asta/cache").exists()


def test_workspace_makefile_requires_ref_without_docs_workflow(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text((WORKSPACE_ASSETS / "Makefile").read_text())
    result = subprocess.run(
        ["make", "check"], cwd=tmp_path, text=True, capture_output=True
    )
    assert result.returncode != 0
    assert "Cannot find the asta-plugins ref" in result.stderr
    assert not (tmp_path / ".asta").exists()


@pytest.mark.parametrize(
    "ref", ["../../outside", "bad;command", "bad'quote", "v1.2.3\ninvalid"]
)
def test_workspace_makefile_rejects_invalid_ref_before_include(
    tmp_path: Path, ref: str
) -> None:
    (tmp_path / "Makefile").write_text((WORKSPACE_ASSETS / "Makefile").read_text())
    result = subprocess.run(
        ["make", "check"],
        cwd=tmp_path,
        env={**os.environ, "ASTA_PLUGINS_REF": ref},
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "Invalid asta-plugins ref" in result.stderr
    assert not (tmp_path / ".asta").exists()


def test_workspace_makefile_clean_works_before_managed_fetch(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text((WORKSPACE_ASSETS / "Makefile").read_text())
    (tmp_path / "_site").mkdir()
    (tmp_path / ".quarto").mkdir()
    result = subprocess.run(
        ["make", "clean"],
        cwd=tmp_path,
        env={
            **os.environ,
            "ASTA_PLUGINS_ARCHIVE_URL": (tmp_path / "missing.tar.gz").as_uri(),
        },
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "_site").exists()
    assert not (tmp_path / ".quarto").exists()
    assert not (tmp_path / ".asta").exists()


def test_workspace_makefile_clean_respects_committed_override(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text((WORKSPACE_ASSETS / "Makefile").read_text())
    (tmp_path / "workspace.mk").write_text(
        "clean:\n\t@echo custom-clean > cleaned-by-project\n"
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "workspace.mk"], cwd=tmp_path, check=True)
    result = subprocess.run(
        ["make", "clean"], cwd=tmp_path, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "cleaned-by-project").read_text().strip() == "custom-clean"
    assert not (tmp_path / ".asta").exists()


def test_workspace_makefile_ref_validation_does_not_run_shell_input(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "unexpected"
    (tmp_path / "Makefile").write_text((WORKSPACE_ASSETS / "Makefile").read_text())
    result = subprocess.run(
        ["make", "check"],
        cwd=tmp_path,
        env={**os.environ, "ASTA_PLUGINS_REF": f"bad'; touch {marker}; #"},
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "Invalid asta-plugins ref" in result.stderr
    assert not marker.exists()


def test_workspace_makefile_ref_validation_does_not_expand_make_input(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "unexpected"
    (tmp_path / "Makefile").write_text((WORKSPACE_ASSETS / "Makefile").read_text())
    result = subprocess.run(
        ["make", "check"],
        cwd=tmp_path,
        env={**os.environ, "ASTA_PLUGINS_REF": f"$(shell touch {marker})"},
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "Invalid asta-plugins ref" in result.stderr
    assert not marker.exists()


@pytest.mark.parametrize("has_managed_asset", [False, True])
def test_workspace_makefile_legacy_fallback(
    tmp_path: Path, has_managed_asset: bool
) -> None:
    archive_root = tmp_path / "source/asta-plugins-old"
    assets = archive_root / WORKSPACE_ASSETS
    assets.mkdir(parents=True)
    legacy_makefile = (
        "legacy:\n\t@echo old-target\n"
        if not has_managed_asset
        else (WORKSPACE_ASSETS / "Makefile").read_text()
    )
    (assets / "Makefile").write_text(legacy_makefile)
    archive = tmp_path / "old.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(archive_root, arcname=archive_root.name)
    project = tmp_path / "project"
    project.mkdir()
    (project / "Makefile").write_text((WORKSPACE_ASSETS / "Makefile").read_text())
    result = subprocess.run(
        ["make", "legacy"],
        cwd=project,
        env={
            **os.environ,
            "ASTA_PLUGINS_REF": "v0.104.1",
            "ASTA_PLUGINS_ARCHIVE_URL": archive.as_uri(),
        },
        text=True,
        capture_output=True,
        timeout=15,
    )
    if has_managed_asset:
        assert result.returncode != 0
        assert "does not provide a managed workspace.mk" in result.stderr
        assert not (project / ".asta/cache/v0.104.1/workspace.mk").exists()
    else:
        assert result.returncode == 0, result.stderr
        assert "old-target" in result.stdout


def test_workspace_makefile_passes_ref_to_evidence_assets(tmp_path: Path) -> None:
    archive_root = tmp_path / "source/asta-plugins-test"
    assets = archive_root / WORKSPACE_ASSETS
    (assets / "_extensions/evidence").mkdir(parents=True)
    (assets / "workspace.mk").write_text(
        (WORKSPACE_ASSETS / "workspace.mk").read_text()
    )
    (assets / "_extensions/evidence/snippet.lua").write_text("-- test\n")
    archive = tmp_path / "assets.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(archive_root, arcname=archive_root.name)
    project = tmp_path / "project"
    project.mkdir()
    (project / "Makefile").write_text((WORKSPACE_ASSETS / "Makefile").read_text())
    result = subprocess.run(
        ["make", "workspace-assets"],
        cwd=project,
        env={
            **os.environ,
            "ASTA_PLUGINS_REF": "v1.2.3",
            "ASTA_PLUGINS_ARCHIVE_URL": archive.as_uri(),
        },
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert "asta-plugins@v1.2.3" in result.stdout
    assert (project / "_extensions/evidence/snippet.lua").read_text() == "-- test\n"


def test_workspace_makefile_latest_uses_same_branch_for_both_assets(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    archive_root = tmp_path / "source/asta-plugins-latest"
    assets = archive_root / WORKSPACE_ASSETS
    (assets / "_extensions/evidence").mkdir(parents=True)
    (assets / "workspace.mk").write_text(
        (WORKSPACE_ASSETS / "workspace.mk").read_text()
    )
    (assets / "_extensions/evidence/snippet.lua").write_text("-- branch\n")
    archive = repo / "archive/refs/heads/latest.tar.gz"
    archive.parent.mkdir(parents=True)
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(archive_root, arcname=archive_root.name)
    project = tmp_path / "project"
    project.mkdir()
    (project / "Makefile").write_text((WORKSPACE_ASSETS / "Makefile").read_text())
    result = subprocess.run(
        ["make", "workspace-assets"],
        cwd=project,
        env={
            **os.environ,
            "ASTA_PLUGINS_REF": "latest",
            "ASTA_PLUGINS_REPO": repo.as_uri(),
        },
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert (project / "_extensions/evidence/snippet.lua").read_text() == "-- branch\n"


def test_workspace_makefile_refreshes_evidence_extension(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive" / "asta-plugins-test"
    source = archive_root / WORKSPACE_ASSETS / "_extensions/evidence"
    shutil.copytree(WORKSPACE_ASSETS / "_extensions/evidence", source)

    archive = tmp_path / "asta-plugins.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(archive_root, arcname=archive_root.name)

    project = tmp_path / "project"
    target = project / "_extensions/evidence"
    target.mkdir(parents=True)
    (target / "stale-file").write_text("remove me")

    env = {
        "ASTA_PLUGINS_ARCHIVE_URL": archive.as_uri(),
        "PATH": os.environ["PATH"],
    }
    subprocess.run(
        [
            "make",
            "-f",
            str((WORKSPACE_ASSETS / "workspace.mk").resolve()),
            "workspace-assets",
        ],
        cwd=project,
        env=env,
        check=True,
    )

    assert not (target / "stale-file").exists()
    assert (target / "snippet.lua").read_bytes() == (
        WORKSPACE_ASSETS / "_extensions/evidence/snippet.lua"
    ).read_bytes()


def _run_workspace_assets(project: Path, archive_url: str) -> str:
    return subprocess.run(
        [
            "make",
            "-f",
            str((WORKSPACE_ASSETS / "workspace.mk").resolve()),
            "workspace-assets",
        ],
        cwd=project,
        env={"ASTA_PLUGINS_ARCHIVE_URL": archive_url, "PATH": os.environ["PATH"]},
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_workspace_makefile_leaves_symlinked_evidence_alone(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "snippet.lua").write_text("-- local edit")
    project = tmp_path / "project"
    (project / "_extensions").mkdir(parents=True)
    (project / "_extensions/evidence").symlink_to(checkout)

    out = _run_workspace_assets(project, (tmp_path / "unreachable.tar.gz").as_uri())

    assert "symlink" in out
    assert (project / "_extensions/evidence").is_symlink()
    assert (checkout / "snippet.lua").read_text() == "-- local edit"


def test_workspace_makefile_leaves_committed_evidence_alone(tmp_path: Path) -> None:
    project = tmp_path / "project"
    target = project / "_extensions/evidence"
    target.mkdir(parents=True)
    (target / "snippet.lua").write_text("-- customized")
    git = ["git", "-C", str(project), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "_extensions/evidence"], check=True)
    subprocess.run([*git, "commit", "-qm", "customize evidence"], check=True)

    out = _run_workspace_assets(project, (tmp_path / "unreachable.tar.gz").as_uri())

    assert "committed" in out
    assert (target / "snippet.lua").read_text() == "-- customized"


def test_workspace_makefile_does_not_race_an_active_install(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive" / "asta-plugins-test"
    source = archive_root / WORKSPACE_ASSETS / "_extensions/evidence"
    shutil.copytree(WORKSPACE_ASSETS / "_extensions/evidence", source)

    archive = tmp_path / "asta-plugins.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(archive_root, arcname=archive_root.name)

    project = tmp_path / "project"
    target = project / "_extensions/evidence"
    target.mkdir(parents=True)
    sentinel = target / "current-version"
    sentinel.write_text("keep me")
    (project / "_extensions/.evidence-install.lock").mkdir()

    env = {
        "ASTA_PLUGINS_ARCHIVE_URL": archive.as_uri(),
        "PATH": os.environ["PATH"],
    }
    result = subprocess.run(
        [
            "make",
            "-f",
            str((WORKSPACE_ASSETS / "workspace.mk").resolve()),
            "workspace-assets",
        ],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "another workspace-assets install is in progress" in result.stderr
    assert sentinel.read_text() == "keep me"


def test_workspace_makefile_keeps_cache_when_offline(tmp_path: Path) -> None:
    # A download failure (no network) with a previously fetched extension must
    # warn and keep the cached copy rather than fail — so a render works offline
    # (e.g. on a plane). Point the archive URL at a file that does not exist to
    # simulate an unreachable upstream.
    project = tmp_path / "project"
    cache = project / "_extensions/evidence"
    cache.mkdir(parents=True)
    sentinel = cache / "snippet.lua"
    sentinel.write_text("cached copy")

    env = {
        "ASTA_PLUGINS_ARCHIVE_URL": (tmp_path / "missing.tar.gz").as_uri(),
        "PATH": os.environ["PATH"],
    }
    result = subprocess.run(
        [
            "make",
            "-f",
            str((WORKSPACE_ASSETS / "workspace.mk").resolve()),
            "workspace-assets",
        ],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert "keeping the cached" in result.stderr
    assert sentinel.read_text() == "cached copy"


def test_workspace_makefile_fails_offline_without_cache(tmp_path: Path) -> None:
    # A download failure with no cached extension is a hard error: the first
    # fetch genuinely needs the network.
    project = tmp_path / "project"
    project.mkdir()

    env = {
        "ASTA_PLUGINS_ARCHIVE_URL": (tmp_path / "missing.tar.gz").as_uri(),
        "PATH": os.environ["PATH"],
    }
    result = subprocess.run(
        [
            "make",
            "-f",
            str((WORKSPACE_ASSETS / "workspace.mk").resolve()),
            "workspace-assets",
        ],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "no cached" in result.stderr
    assert not (project / "_extensions/evidence").exists()


def _write_fake_gh(bin_dir: Path) -> None:
    fake = bin_dir / "gh"
    fake.write_text(
        """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$GH_LOG"
case "$1 $2" in
  "repo view") echo owner/project ;;
  "run list")
    count=0
    [ ! -f "$GH_RUN_COUNT" ] || count=$(cat "$GH_RUN_COUNT")
    count=$((count + 1))
    printf '%s\\n' "$count" > "$GH_RUN_COUNT"
    [ "${GH_RUN_FAIL_ON:-0}" != "$count" ] || {
      echo '{"message":"temporary failure"}'
      exit 1
    }
    if [ "$count" -eq 1 ]; then
      echo "${GH_BEFORE_RUN:-100}"
    elif [ "$count" -ge "${GH_RUN_ON:-2}" ]; then
      echo "101"
    fi
    ;;
  "run view") echo "${GH_RUN_STATUS:-completed} ${GH_RUN_CONCLUSION:-success}" ;;
  "api repos/owner/project/branches/gh-pages")
    count=0
    [ ! -f "$GH_TIP_COUNT" ] || count=$(cat "$GH_TIP_COUNT")
    count=$((count + 1))
    printf '%s\\n' "$count" > "$GH_TIP_COUNT"
    if [ "$count" -eq 1 ] && [ "${GH_NO_BASELINE_BRANCH:-0}" = 1 ]; then
      echo 'gh: Not Found (HTTP 404)' >&2
      exit 1
    fi
    if [ "$count" -eq 1 ]; then echo before; else echo "${GH_AFTER_TIP:-before}"; fi
    ;;
  "api repos/owner/project/compare/before..."*)
    [ "${GH_COMPARE_FAIL:-0}" != 1 ] || {
      echo '{"message":"temporary failure"}'
      exit 1
    }
    jq_filter=
    while [ "$#" -gt 0 ]; do
      if [ "$1" = --jq ]; then jq_filter=$2; break; fi
      shift
    done
    marker_run=${GH_MARKER_RUN:-101}
    printf '{"status":"ahead","total_commits":1,"commits":[{"sha":"published-sha","commit":{"message":"Deploy pull_request abc (run %s)\\\\n"}}]}\\n' "$marker_run" | jq -r "$jq_filter"
    ;;
  "api repos/owner/project/commits?sha=gh-pages&per_page=100")
    jq_filter=
    while [ "$#" -gt 0 ]; do
      if [ "$1" = --jq ]; then jq_filter=$2; break; fi
      shift
    done
    marker_run=${GH_MARKER_RUN:-101}
    printf '[{"sha":"published-sha","commit":{"message":"Deploy pull_request abc (run %s)\\\\n"}}]\\n' "$marker_run" | jq -r "$jq_filter"
    ;;
  "api repos/owner/project/pages/builds?per_page=10")
    [ "${GH_PAGES_API_FAIL:-0}" != 1 ] || exit 1
    echo "${GH_BUILT:-1}"
    ;;
  *) echo "unexpected gh invocation: $*" >&2; exit 2 ;;
esac
"""
    )
    fake.chmod(0o755)


def _preview_project(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "seed",
            "--no-gpg-sign",
        ],
        cwd=project,
        check=True,
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_gh(bin_dir)
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GH_LOG": str(tmp_path / "gh.log"),
        "GH_RUN_COUNT": str(tmp_path / "run-count"),
        "GH_TIP_COUNT": str(tmp_path / "tip-count"),
        "WORKFLOW_TIMEOUT": "3",
        "RUN_TIMEOUT": "2",
        "PAGES_TIMEOUT": "2",
        "POLL": "1",
    }
    return project, env


def test_preview_wait_retries_lookup_from_detached_head(tmp_path: Path) -> None:
    project, env = _preview_project(tmp_path)
    script = (WORKSPACE_ASSETS / "wait-for-preview.sh").resolve()

    subprocess.run([script, "baseline"], cwd=project, env=env, check=True)
    subprocess.run(["git", "checkout", "--detach", "-q"], cwd=project, check=True)
    env.update(GH_RUN_ON="3", GH_RUN_FAIL_ON="2", GH_AFTER_TIP="after")
    result = subprocess.run(
        [script, "wait"], cwd=project, env=env, text=True, capture_output=True
    )

    assert result.returncode == 0, result.stderr
    assert "Pages published published-sha" in result.stdout
    run_lookups = [
        line
        for line in Path(env["GH_LOG"]).read_text().splitlines()
        if "run list" in line
    ]
    assert all("--branch" not in line for line in run_lookups)


def test_preview_wait_matches_pages_build_to_workflow_deployment(
    tmp_path: Path,
) -> None:
    project, env = _preview_project(tmp_path)
    script = (WORKSPACE_ASSETS / "wait-for-preview.sh").resolve()

    subprocess.run([script, "baseline"], cwd=project, env=env, check=True)
    env["GH_AFTER_TIP"] = "after"
    result = subprocess.run(
        [script, "wait"], cwd=project, env=env, text=True, capture_output=True
    )

    assert result.returncode == 0, result.stderr
    assert "Pages published published-sha" in result.stdout
    log = Path(env["GH_LOG"]).read_text()
    assert "compare/before...after" in log
    assert "(run 101)" in log
    assert "pages/builds?per_page=10" in log


def test_preview_wait_rejects_an_unidentified_pages_update(tmp_path: Path) -> None:
    project, env = _preview_project(tmp_path)
    script = (WORKSPACE_ASSETS / "wait-for-preview.sh").resolve()

    subprocess.run([script, "baseline"], cwd=project, env=env, check=True)
    env.update(GH_AFTER_TIP="after", GH_MARKER_RUN="999")
    result = subprocess.run(
        [script, "wait"], cwd=project, env=env, text=True, capture_output=True
    )

    assert result.returncode == 1
    assert "no identifiable run-ID marker" in result.stderr
    assert (project / ".git/preview-run-before").exists()


def test_preview_wait_supports_initial_pages_deployment(tmp_path: Path) -> None:
    project, env = _preview_project(tmp_path)
    script = (WORKSPACE_ASSETS / "wait-for-preview.sh").resolve()
    env.update(GH_NO_BASELINE_BRANCH="1", GH_AFTER_TIP="first-pages-tip")

    baseline = subprocess.run(
        [script, "baseline"], cwd=project, env=env, text=True, capture_output=True
    )
    result = subprocess.run(
        [script, "wait"], cwd=project, env=env, text=True, capture_output=True
    )

    assert baseline.returncode == 0, baseline.stderr
    assert result.returncode == 0, result.stderr
    assert "Pages published published-sha" in result.stdout
    assert "commits?sha=gh-pages&per_page=100" in Path(env["GH_LOG"]).read_text()


def test_preview_wait_preserves_baseline_when_correlation_fails(
    tmp_path: Path,
) -> None:
    project, env = _preview_project(tmp_path)
    script = (WORKSPACE_ASSETS / "wait-for-preview.sh").resolve()

    subprocess.run([script, "baseline"], cwd=project, env=env, check=True)
    env.update(GH_AFTER_TIP="after", GH_COMPARE_FAIL="1")
    result = subprocess.run(
        [script, "wait"], cwd=project, env=env, text=True, capture_output=True
    )

    assert result.returncode == 1
    assert "Could not correlate" in result.stderr
    assert (project / ".git/preview-run-before").exists()


def test_preview_wait_preserves_baseline_for_retry(tmp_path: Path) -> None:
    project, env = _preview_project(tmp_path)
    script = (WORKSPACE_ASSETS / "wait-for-preview.sh").resolve()

    subprocess.run([script, "baseline"], cwd=project, env=env, check=True)
    env.update(GH_RUN_ON="3", WORKFLOW_TIMEOUT="1", GH_AFTER_TIP="after")
    first = subprocess.run(
        [script, "wait"], cwd=project, env=env, text=True, capture_output=True
    )
    assert first.returncode == 1
    assert (project / ".git/preview-run-before").exists()

    second = subprocess.run(
        [script, "wait"], cwd=project, env=env, text=True, capture_output=True
    )
    assert second.returncode == 0, second.stderr
    assert not (project / ".git/preview-run-before").exists()


def test_preview_wait_bounds_workflow_completion(tmp_path: Path) -> None:
    project, env = _preview_project(tmp_path)
    script = (WORKSPACE_ASSETS / "wait-for-preview.sh").resolve()

    subprocess.run([script, "baseline"], cwd=project, env=env, check=True)
    env.update(GH_RUN_STATUS="queued", RUN_TIMEOUT="1")
    result = subprocess.run(
        [script, "wait"], cwd=project, env=env, text=True, capture_output=True
    )

    assert result.returncode == 1
    assert "did not complete within 1s" in result.stderr
    assert (project / ".git/preview-run-before").exists()


def test_preview_wait_reports_unreadable_pages_api(tmp_path: Path) -> None:
    project, env = _preview_project(tmp_path)
    script = (WORKSPACE_ASSETS / "wait-for-preview.sh").resolve()

    subprocess.run([script, "baseline"], cwd=project, env=env, check=True)
    env.update(GH_AFTER_TIP="after", GH_PAGES_API_FAIL="1", PAGES_TIMEOUT="1")
    result = subprocess.run(
        [script, "wait"], cwd=project, env=env, text=True, capture_output=True
    )

    assert result.returncode == 1
    assert "Could not read Pages builds" in result.stderr
    assert "verify Pages API access" in result.stderr
    assert (project / ".git/preview-run-before").exists()


def test_preview_wait_rejects_invalid_timing(tmp_path: Path) -> None:
    project, env = _preview_project(tmp_path)
    script = (WORKSPACE_ASSETS / "wait-for-preview.sh").resolve()
    env["POLL"] = "0"

    result = subprocess.run(
        [script, "baseline"], cwd=project, env=env, text=True, capture_output=True
    )

    assert result.returncode == 2
    assert "POLL must be a positive integer" in result.stderr


def test_preview_baseline_surfaces_run_lookup_failure(tmp_path: Path) -> None:
    project, env = _preview_project(tmp_path)
    script = (WORKSPACE_ASSETS / "wait-for-preview.sh").resolve()
    env["GH_RUN_FAIL_ON"] = "1"

    result = subprocess.run(
        [script, "baseline"], cwd=project, env=env, text=True, capture_output=True
    )

    assert result.returncode == 1
    assert "Could not read workflow runs" in result.stderr


def test_preview_wait_bounds_pages_poll_and_preserves_baseline(tmp_path: Path) -> None:
    project, env = _preview_project(tmp_path)
    script = (WORKSPACE_ASSETS / "wait-for-preview.sh").resolve()

    subprocess.run([script, "baseline"], cwd=project, env=env, check=True)
    env.update(GH_AFTER_TIP="after", GH_BUILT="0", PAGES_TIMEOUT="1")
    result = subprocess.run(
        [script, "wait"], cwd=project, env=env, text=True, capture_output=True
    )

    assert result.returncode == 1
    assert "Pages did not publish" in result.stderr
    assert (project / ".git/preview-run-before").exists()


def _make_evidence_archive(archive: Path) -> None:
    """Write a tarball whose layout mirrors an asta-plugins source archive."""
    archive_root = archive.parent / "asta-plugins-test"
    source = archive_root / WORKSPACE_ASSETS / "_extensions/evidence"
    if source.exists():
        shutil.rmtree(source)
    shutil.copytree(WORKSPACE_ASSETS / "_extensions/evidence", source)
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(archive_root, arcname=archive_root.name)


def test_workspace_makefile_resolves_latest_version_tag(tmp_path: Path) -> None:
    # A local git repo standing in for asta-plugins: git ls-remote reads its
    # tags, and curl reads a co-located archive/ dir via file://. The default
    # (no ASTA_PLUGINS_REF, no ASTA_PLUGINS_ARCHIVE_URL) must pick the highest
    # semver tag and skip non-version tags.
    repo = tmp_path / "asta-plugins"
    (repo / "archive").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "seed",
            "--no-gpg-sign",
        ],
        check=True,
    )
    for tag in ("v0.2.0", "v0.10.0", "v0.9.0", "v2-reproduction-work"):
        subprocess.run(["git", "-C", str(repo), "tag", tag], check=True)

    # Only the latest semver tag's archive exists; if resolution picked any
    # other ref (main, v2-reproduction-work, v0.9.0), the curl would 404.
    _make_evidence_archive(repo / "archive/v0.10.0.tar.gz")

    project = tmp_path / "project"
    project.mkdir()
    env = {
        "ASTA_PLUGINS_REPO": repo.as_uri(),
        "PATH": os.environ["PATH"],
    }
    result = subprocess.run(
        [
            "make",
            "-f",
            str((WORKSPACE_ASSETS / "workspace.mk").resolve()),
            "workspace-assets",
        ],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert "asta-plugins@v0.10.0" in result.stdout
    assert (project / "_extensions/evidence/snippet.lua").read_bytes() == (
        WORKSPACE_ASSETS / "_extensions/evidence/snippet.lua"
    ).read_bytes()
