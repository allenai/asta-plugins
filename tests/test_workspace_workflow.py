import os
import re
import shlex
import shutil
import subprocess
import tarfile
import tomllib
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(".github/workflows/workspace-quarto-site.yml")
WORKSPACE_ASSETS = Path("plugins/asta-tools/skills/workspace/assets")


def _run_paper_step(
    tmp_path: Path,
    *,
    download_fails: bool = False,
    prepare=None,
    inspect_stage: bool = False,
    paper_script: str | None = None,
    worktree_add_fails: bool = False,
    update_ref_fails: bool = False,
):
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
    pr_base = prepare(project) if prepare else ""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(
        '#!/bin/sh\n[ "${FAIL_CURL:-0}" != 1 ] || exit 1\n'
        'if [ -n "${PAPER_SOURCE:-}" ] && [ "${2#*paper-preview.sh}" != "$2" ]; then\n'
        '  cp "$PAPER_SOURCE" "$4"\n'
        "else\n"
        '  cp "$DISCOVERY_SOURCE" "$4"\n'
        "fi\n"
    )
    curl.chmod(0o755)
    sudo = bin_dir / "sudo"
    sudo.write_text(
        "#!/bin/sh\n"
        'if [ -n "${INSPECT_STAGE_PATH:-}" ]; then\n'
        '  git diff-tree --no-commit-id --name-only -r HEAD > "$INSPECT_STAGE_PATH"\n'
        "fi\n"
        '[ -n "${PAPER_SOURCE:-}" ]\n'
    )
    sudo.chmod(0o755)
    if worktree_add_fails or update_ref_fails:
        git = bin_dir / "git"
        git.write_text(
            "#!/bin/sh\n"
            + (
                'if [ "$1" = worktree ] && [ "$2" = add ]; then exit 1; fi\n'
                if worktree_add_fails
                else ""
            )
            + (
                'if [ "$1" = -C ] && [ "$3" = update-ref ]; then exit 1; fi\n'
                if update_ref_fails
                else ""
            )
            + f'exec {shutil.which("git")} "$@"\n'
        )
        git.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "PR_BASE": pr_base,
        "DISCOVERY_SOURCE": str(source.resolve()),
        "FAIL_CURL": "1" if download_fails else "0",
    }
    if inspect_stage:
        env["INSPECT_STAGE_PATH"] = str(tmp_path / "staged.txt")
    if paper_script is not None:
        source = tmp_path / "paper-preview.sh"
        source.write_text(paper_script)
        env["PAPER_SOURCE"] = str(source)
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


def _git(project: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _generated_paper_project(project: Path) -> str:
    (project / ".gitignore").write_text("gen/\n_site/\n")
    (project / "Makefile").write_text(
        "check:\n\t@true\n"
        "latex:\n\tmkdir -p gen\n\techo paper > gen/main.tex\n"
        "\techo rc > gen/latexmkrc\n"
    )
    _git(project, "init", "-q")
    _git(project, "add", ".")
    _git(project, "commit", "-q", "-m", "base")
    return _git(project, "rev-parse", "HEAD")


def test_generated_latex_survives_failed_toolchain_without_commit(
    tmp_path: Path,
) -> None:
    project, result = _run_paper_step(tmp_path, prepare=_generated_paper_project)

    assert result.returncode != 0
    assert (
        project / "_site/paper-previews/gen/build-failed.txt"
    ).read_text().strip() == ("Could not update LaTeX package lists.")
    assert (project / "gen/main.tex").read_text().strip() == "paper"
    assert _git(project, "log", "--format=%s") == "base"
    assert _git(project, "diff", "--cached", "--name-only") == ""
    assert len(_git(project, "worktree", "list").splitlines()) == 1


def test_generated_paths_are_literal_and_check_edits_survive(tmp_path: Path) -> None:
    def prepare(project: Path) -> str:
        (project / "genx").mkdir()
        (project / "genx/main.tex").write_text("committed elsewhere\n")
        (project / "status.txt").write_text("source\n")
        (project / "Makefile").write_text(
            "check:\n\tprintf rendered > status.txt\n"
            "latex:\n\tmkdir -p 'gen[x]'\n"
            "\tprintf generated > 'gen[x]/main.tex'\n"
            "\tprintf rc > 'gen[x]/latexmkrc'\n"
            "\tprintf figure > 'gen[x]/main*.pdf'\n"
            "\tprintf output > 'gen[x]/main.pdf'\n"
        )
        _git(project, "init", "-q")
        _git(
            project, "add", "Makefile", "status.txt", "paper/main.tex", "genx/main.tex"
        )
        _git(project, "commit", "-q", "-m", "base")
        base = _git(project, "rev-parse", "HEAD")
        hook = project / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        _git(project, "config", "commit.gpgsign", "true")
        subprocess.run(["make", "check"], cwd=project, check=True, capture_output=True)
        return base

    project, result = _run_paper_step(
        tmp_path,
        prepare=prepare,
        inspect_stage=True,
        paper_script="#!/bin/sh\nexit 0\n",
    )

    assert result.returncode == 0, result.stderr
    assert set((tmp_path / "staged.txt").read_text().splitlines()) == {
        "gen[x]/latexmkrc",
        "gen[x]/main.tex",
        "gen[x]/main*.pdf",
    }
    assert (project / "status.txt").read_text() == "rendered"
    assert (project / "gen[x]/main.pdf").read_text() == "output"
    assert _git(project, "diff", "--cached", "--name-only") == ""
    assert _git(project, "log", "--format=%s") == "base"


def test_latex_prerequisite_is_not_a_target(tmp_path: Path) -> None:
    def prepare(project: Path) -> str:
        (project / "Makefile").write_text("all: latex\n")
        _git(project, "init", "-q")
        _git(project, "add", "Makefile", "paper/main.tex")
        _git(project, "commit", "-q", "-m", "base")
        return _git(project, "rev-parse", "HEAD")

    project, result = _run_paper_step(tmp_path, prepare=prepare)

    assert result.returncode != 0
    assert "No rule to make target 'latex'" not in result.stderr
    assert not (project / "_site/paper-previews/build-failed.txt").exists()
    assert (project / "_site/paper-previews/paper/build-failed.txt").is_file()


def test_paper_generated_by_check_is_discovered_without_staging_artifacts(
    tmp_path: Path,
) -> None:
    def prepare(project: Path) -> str:
        base = _generated_paper_project(project)
        generated = project / "gen"
        generated.mkdir()
        (generated / "main.tex").write_text("paper")
        (generated / "latexmkrc").write_text("rc")
        (generated / "figure.pdf").write_text("figure")
        (generated / "main.pdf").write_text("built paper")
        (generated / "main.aux").write_text("build artifact")
        (generated / ".env").write_text("local file")
        return base

    project, result = _run_paper_step(tmp_path, prepare=prepare, inspect_stage=True)

    assert result.returncode != 0
    assert (project / "_site/paper-previews/gen/build-failed.txt").is_file()
    assert set((tmp_path / "staged.txt").read_text().splitlines()) == {
        "gen/figure.pdf",
        "gen/latexmkrc",
        "gen/main.tex",
    }
    assert _git(project, "diff", "--cached", "--name-only") == ""


def test_missing_latex_target_keeps_existing_paper(tmp_path: Path) -> None:
    def prepare(project: Path) -> str:
        (project / "Makefile").write_text("check:\n\t@true\n")
        _git(project, "init", "-q")
        _git(project, "add", ".")
        _git(project, "commit", "-q", "-m", "base")
        return _git(project, "rev-parse", "HEAD")

    project, result = _run_paper_step(tmp_path, prepare=prepare)

    assert result.returncode != 0
    assert (project / "_site/paper-previews/paper/build-failed.txt").is_file()
    assert not (project / "_site/paper-previews/build-failed.txt").exists()


def test_base_without_latex_target_skips_check(tmp_path: Path) -> None:
    def prepare(project: Path) -> str:
        (project / "Makefile").write_text("check:\n\t@false\n")
        _git(project, "init", "-q")
        _git(project, "add", ".")
        _git(project, "commit", "-q", "-m", "base")
        return _git(project, "rev-parse", "HEAD")

    project, result = _run_paper_step(
        tmp_path, prepare=prepare, paper_script="#!/bin/sh\nexit 0\n"
    )

    assert result.returncode == 0, result.stderr
    assert "make check failed on the PR base" not in result.stdout
    assert not (project / "_site/paper-previews/build-failed.txt").exists()


def test_generated_base_and_head_keep_distinct_sources(tmp_path: Path) -> None:
    def prepare(project: Path) -> str:
        base = _generated_paper_project(project)
        makefile = project / "Makefile"
        makefile.write_text(makefile.read_text().replace("echo paper", "echo changed"))
        _git(project, "add", "Makefile")
        _git(project, "commit", "-q", "-m", "change")
        return base

    paper_script = (
        "#!/bin/bash\n"
        'if [ "$2" = gen ]; then\n'
        '  git show "$1:gen/main.tex" > _site/base-paper.txt\n'
        "  cp gen/main.tex _site/head-paper.txt\n"
        "fi\n"
    )
    project, result = _run_paper_step(
        tmp_path, prepare=prepare, paper_script=paper_script
    )

    assert result.returncode == 0, result.stderr
    assert (project / "_site/base-paper.txt").read_text().strip() == "paper"
    assert (project / "_site/head-paper.txt").read_text().strip() == "changed"
    assert _git(project, "log", "--format=%s") == "change\nbase"
    assert _git(project, "diff", "--cached", "--name-only") == ""
    assert len(_git(project, "worktree", "list").splitlines()) == 1


def test_generated_shared_inputs_are_available_on_base_and_head(tmp_path: Path) -> None:
    def prepare(project: Path) -> str:
        (project / ".gitignore").write_text(
            "gen/\nshared/\ndata/\nprivate.bib\n_site/\n"
        )
        (project / "source.txt").write_text("before\n")
        (project / "Makefile").write_text(
            "check:\n\t@true\n"
            "latex:\n\tmkdir -p gen shared data\n"
            "\tcp source.txt gen/main.tex\n"
            "\tprintf rc > gen/latexmkrc\n"
            "\tcp source.txt shared/citations.sty\n"
            "\tcp source.txt data/table.csv\n"
            "\tprintf private > private.bib\n"
            "\tprintf '%s\\n' shared/citations.sty data/table.csv >> "
            '"$$ASTA_PAPER_INPUTS_FILE"\n'
        )
        _git(project, "init", "-q")
        _git(project, "add", ".gitignore", "Makefile", "source.txt", "paper/main.tex")
        _git(project, "commit", "-q", "-m", "base")
        base = _git(project, "rev-parse", "HEAD")
        (project / "source.txt").write_text("after\n")
        _git(project, "add", "source.txt")
        _git(project, "commit", "-q", "-m", "change")
        return base

    paper_script = (
        "#!/bin/bash\n"
        'git show "$1:shared/citations.sty" > _site/base-style.txt\n'
        'git show "$1:data/table.csv" > _site/base-table.txt\n'
        "git show HEAD:shared/citations.sty > _site/head-style.txt\n"
        "git show HEAD:data/table.csv > _site/head-table.txt\n"
        "if git cat-file -e HEAD:private.bib 2>/dev/null; then exit 1; fi\n"
    )
    project, result = _run_paper_step(
        tmp_path, prepare=prepare, paper_script=paper_script, inspect_stage=True
    )

    assert result.returncode == 0, result.stderr
    assert (project / "_site/base-style.txt").read_text() == "before\n"
    assert (project / "_site/base-table.txt").read_text() == "before\n"
    assert (project / "_site/head-style.txt").read_text() == "after\n"
    assert (project / "_site/head-table.txt").read_text() == "after\n"
    assert set((tmp_path / "staged.txt").read_text().splitlines()) == {
        "gen/main.tex",
        "gen/latexmkrc",
        "shared/citations.sty",
        "data/table.csv",
    }
    assert _git(project, "diff", "--cached", "--name-only") == ""


@pytest.mark.parametrize(
    "bad_path",
    [
        "../outside",
        "/tmp/absolute",
        ".git/config",
        "shared/link.txt",
        "linked/child.txt",
    ],
)
def test_invalid_generated_shared_input_is_rejected(
    tmp_path: Path, bad_path: str
) -> None:
    def prepare(project: Path) -> str:
        (project / ".gitignore").write_text("gen/\n_site/\n")
        (project / "Makefile").write_text(
            "latex:\n\tmkdir -p gen\n\tprintf paper > gen/main.tex\n"
            "\tprintf rc > gen/latexmkrc\n"
            f"\tprintf '%s\\n' {shlex.quote(bad_path)} >> \"$$ASTA_PAPER_INPUTS_FILE\"\n"
        )
        (project / "shared").mkdir()
        (project / "shared/child.txt").write_text("input\n")
        (project / "shared/link.txt").symlink_to(project / "paper/main.tex")
        (project / "linked").symlink_to(project / "shared", target_is_directory=True)
        _git(project, "init", "-q")
        _git(project, "add", ".gitignore", "Makefile", "paper/main.tex")
        _git(project, "commit", "-q", "-m", "base")
        return _git(project, "rev-parse", "HEAD")

    project, result = _run_paper_step(tmp_path, prepare=prepare)

    assert result.returncode != 0
    assert (
        "paper input" in result.stderr.lower()
        or "ASTA_PAPER_INPUTS_FILE" in result.stderr
    )
    assert _git(project, "diff", "--cached", "--name-only") == ""


def test_base_check_prepares_inputs_for_generated_paper(tmp_path: Path) -> None:
    def prepare(project: Path) -> str:
        (project / ".gitignore").write_text("gen/\n_site/\n")
        (project / "Makefile").write_text(
            "check:\n\tmkdir -p gen\n\tcp source.txt gen/input.txt\n"
            "latex:\n\tmkdir -p gen\n\tcp gen/input.txt gen/main.tex\n"
            "\techo rc > gen/latexmkrc\n"
        )
        (project / "source.txt").write_text("before\n")
        _git(project, "init", "-q")
        _git(project, "add", ".gitignore", "Makefile", "source.txt")
        _git(project, "commit", "-q", "-m", "base")
        base = _git(project, "rev-parse", "HEAD")
        (project / "source.txt").write_text("after\n")
        _git(project, "add", "source.txt")
        _git(project, "commit", "-q", "-m", "change")
        subprocess.run(["make", "check"], cwd=project, check=True, capture_output=True)
        return base

    paper_script = (
        "#!/bin/bash\n"
        'git show "$1:gen/main.tex" > _site/base-paper.txt\n'
        "cp gen/main.tex _site/head-paper.txt\n"
    )
    project, result = _run_paper_step(
        tmp_path, prepare=prepare, paper_script=paper_script
    )

    assert result.returncode == 0, result.stderr
    assert (project / "_site/base-paper.txt").read_text() == "before\n"
    assert (project / "_site/head-paper.txt").read_text() == "after\n"
    assert _git(project, "diff", "--cached", "--name-only") == ""
    assert len(_git(project, "worktree", "list").splitlines()) == 1


def test_base_worktree_failure_reports_discovery_error(tmp_path: Path) -> None:
    project, result = _run_paper_step(
        tmp_path,
        prepare=_generated_paper_project,
        worktree_add_fails=True,
    )

    assert result.returncode != 0
    assert (
        project / "_site/paper-previews/build-failed.txt"
    ).read_text().strip() == "Could not create a worktree for the PR base."
    assert _git(project, "diff", "--cached", "--name-only") == ""
    assert len(_git(project, "worktree", "list").splitlines()) == 1


def test_base_latex_failure_keeps_head_preview(tmp_path: Path) -> None:
    def prepare(project: Path) -> str:
        (project / ".gitignore").write_text("gen/\n_site/\n")
        (project / "Makefile").write_text(
            "check:\n\t@true\nlatex: missing-prerequisite\n"
        )
        _git(project, "init", "-q")
        _git(project, "add", ".")
        _git(project, "commit", "-q", "-m", "base")
        base = _git(project, "rev-parse", "HEAD")
        (project / "Makefile").write_text(
            "latex:\n\tmkdir -p gen\n\techo paper > gen/main.tex\n"
            "\techo rc > gen/latexmkrc\n"
        )
        _git(project, "add", "Makefile")
        _git(project, "commit", "-q", "-m", "fix")
        return base

    project, result = _run_paper_step(tmp_path, prepare=prepare)

    assert result.returncode != 0
    assert "make latex failed on the PR base" in result.stdout
    assert (project / "_site/paper-previews/gen/build-failed.txt").is_file()
    assert _git(project, "log", "--format=%s") == "fix\nbase"


def test_base_check_failure_keeps_head_preview(tmp_path: Path) -> None:
    def prepare(project: Path) -> str:
        (project / ".gitignore").write_text("gen/\n_site/\n")
        (project / "Makefile").write_text(
            "check: missing-prerequisite\nlatex:\n\t@true\n"
        )
        _git(project, "init", "-q")
        _git(project, "add", ".")
        _git(project, "commit", "-q", "-m", "base")
        base = _git(project, "rev-parse", "HEAD")
        (project / "Makefile").write_text(
            "check:\n\t@true\n"
            "latex:\n\tmkdir -p gen\n\techo paper > gen/main.tex\n"
            "\techo rc > gen/latexmkrc\n"
        )
        _git(project, "add", "Makefile")
        _git(project, "commit", "-q", "-m", "fix")
        return base

    project, result = _run_paper_step(tmp_path, prepare=prepare)

    assert result.returncode != 0
    assert "make check failed on the PR base" in result.stdout
    assert (project / "_site/paper-previews/gen/build-failed.txt").is_file()
    assert _git(project, "log", "--format=%s") == "fix\nbase"


def test_broken_latex_target_fails_discovery(tmp_path: Path) -> None:
    def prepare(project: Path) -> str:
        (project / "Makefile").write_text("latex: missing-prerequisite\n")
        _git(project, "init", "-q")
        _git(project, "add", ".")
        _git(project, "commit", "-q", "-m", "base")
        return _git(project, "rev-parse", "HEAD")

    project, result = _run_paper_step(tmp_path, prepare=prepare)

    assert result.returncode != 0
    assert "No rule to make target 'missing-prerequisite'" in result.stderr
    assert (project / "_site/paper-previews/build-failed.txt").read_text().strip() == (
        "make latex failed; see the build log."
    )


def test_broken_latex_target_still_builds_committed_paper(tmp_path: Path) -> None:
    def prepare(project: Path) -> str:
        (project / "Makefile").write_text("latex: missing-prerequisite\n")
        _git(project, "init", "-q")
        _git(project, "add", ".")
        _git(project, "commit", "-q", "-m", "base")
        return _git(project, "rev-parse", "HEAD")

    project, result = _run_paper_step(
        tmp_path,
        prepare=prepare,
        paper_script="#!/bin/sh\nprintf built > _site/paper-built.txt\n",
    )

    assert result.returncode != 0
    assert (project / "_site/paper-built.txt").read_text() == "built"
    assert (project / "_site/paper-previews/build-failed.txt").is_file()


def test_committed_paper_is_not_replaced_by_latex_target(tmp_path: Path) -> None:
    def prepare(project: Path) -> str:
        (project / "Makefile").write_text("latex:\n\techo generated > paper/main.tex\n")
        _git(project, "init", "-q")
        _git(project, "add", ".")
        _git(project, "commit", "-q", "-m", "base")
        return _git(project, "rev-parse", "HEAD")

    project, result = _run_paper_step(tmp_path, prepare=prepare)

    assert result.returncode != 0
    assert (project / "paper/main.tex").read_text() == "paper"
    assert _git(project, "diff", "--cached", "--name-only") == ""


def test_check_edit_to_committed_paper_survives_latex_target(tmp_path: Path) -> None:
    def prepare(project: Path) -> str:
        (project / "Makefile").write_text("latex:\n\techo generated > paper/main.tex\n")
        _git(project, "init", "-q")
        _git(project, "add", ".")
        _git(project, "commit", "-q", "-m", "base")
        (project / "paper/main.tex").write_text("checked\n")
        return _git(project, "rev-parse", "HEAD")

    project, result = _run_paper_step(
        tmp_path,
        prepare=prepare,
        paper_script="#!/bin/sh\ncp paper/main.tex _site/paper-source.txt\n",
    )

    assert result.returncode == 0, result.stderr
    assert (project / "paper/main.tex").read_text() == "checked\n"
    assert (project / "_site/paper-source.txt").read_text() == "checked\n"


def test_failed_temporary_commit_clears_generated_index(tmp_path: Path) -> None:
    project, result = _run_paper_step(
        tmp_path,
        prepare=_generated_paper_project,
        update_ref_fails=True,
        paper_script="#!/bin/sh\nexit 0\n",
    )

    assert result.returncode != 0
    assert (project / "_site/paper-previews/build-failed.txt").is_file()
    assert _git(project, "diff", "--cached", "--name-only") == ""
    assert _git(project, "log", "--format=%s") == "base"


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
            str((WORKSPACE_ASSETS / "Makefile").resolve()),
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
            str((WORKSPACE_ASSETS / "Makefile").resolve()),
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
            str((WORKSPACE_ASSETS / "Makefile").resolve()),
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
            str((WORKSPACE_ASSETS / "Makefile").resolve()),
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
            str((WORKSPACE_ASSETS / "Makefile").resolve()),
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
            str((WORKSPACE_ASSETS / "Makefile").resolve()),
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
