"""Exercise the paper preview's Git and artifact flow with fake TeX commands."""

import json
import os
import subprocess
from pathlib import Path

SCRIPT = (
    Path(__file__).parents[1]
    / "plugins/asta-tools/skills/workspace/assets/paper-preview.sh"
)


def run(*args, cwd, env=None):
    return subprocess.run(
        args, cwd=cwd, env=env, check=True, capture_output=True, text=True
    )


def paper_repo(tmp_path, old_paper=True):
    repo = tmp_path / "repo"
    repo.mkdir()
    run("git", "init", "-q", cwd=repo)
    run("git", "config", "user.email", "test@example.invalid", cwd=repo)
    run("git", "config", "user.name", "Test", cwd=repo)
    if old_paper:
        (repo / "paper").mkdir()
        (repo / "paper/main.tex").write_text("old")
        run("git", "add", "paper/main.tex", cwd=repo)
        run("git", "commit", "-qm", "base", cwd=repo)
    else:
        run("git", "commit", "--allow-empty", "-qm", "base", cwd=repo)
    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    (repo / "paper").mkdir(exist_ok=True)
    (repo / "paper/main.tex").write_text("new")
    run("git", "add", "paper/main.tex", cwd=repo)
    run("git", "commit", "-qm", "edit", cwd=repo)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    commands = {
        "latexmk": '#!/bin/bash\nmkdir -p build\nname="${@: -1}"\nprintf pdf > "build/${name%.tex}.pdf"\nprintf "%s\\n" "${FAKE_LATEX_LOG:-}" > build/main.log\nif [ -n "${FAKE_BIBTEX_LOG:-}" ]; then printf "%s\\n" "$FAKE_BIBTEX_LOG" > build/main.blg; fi\nif [ -n "${FAKE_BBL:-}" ]; then printf "%s\\n" "$FAKE_BBL" > build/main.bbl; fi\nprintf "PWD %s\\nINPUT main.tex\\n" "$PWD" > build/main.fls\nif [ -n "${FAKE_LATEX_INPUT:-}" ]; then printf "INPUT %s\\n" "$FAKE_LATEX_INPUT" >> build/main.fls; fi\n',
        "latexdiff": "#!/bin/bash\nprintf '\\\\begin{document}\\n\\\\DIFadd{new}\\n'\n",
        "pdftoppm": '#!/bin/bash\nname="${@: -1}"\nprintf png > "${name}-1.png"\n',
    }
    for name, contents in commands.items():
        path = bin_dir / name
        path.write_text(contents)
        path.chmod(0o755)
    with (bin_dir / "latexmk").open("a") as mock:
        mock.write('printf "%s\\n" "$*" >> latexmk-args.txt\n')
        mock.write(
            'printf "build/main.pdf: main.tex %s\\n" "$FAKE_LATEX_DEPS" > build/main.dep\n'
        )
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FAKE_LATEX_DEPS"] = ""
    return repo, base, env, bin_dir


def test_paper_preview_builds_current_and_diff_pdfs(tmp_path):
    repo, base, env, _ = paper_repo(tmp_path)

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert (repo / "_site/paper/main.pdf").exists()
    assert (repo / "_site/paper/what-changed.pdf").exists()
    assert (repo / "_site/paper/diff-page-1.png").exists()
    assert json.loads((repo / "_site/paper/preview.json").read_text()) == {
        "changed": True,
        "diff": True,
        "other_inputs": False,
        "thumbnail_limit": 12,
    }
    assert not list((repo / "paper").glob("what-changed.*.tex"))
    commands = (repo / "paper/latexmk-args.txt").read_text().splitlines()
    assert len(commands) == 2
    assert all("-pdf" not in command for command in commands)
    assert all("$pdf_mode ||= 1;" in command for command in commands)


def test_new_paper_links_current_pdf_without_diff_warning(tmp_path):
    repo, base, env, _ = paper_repo(tmp_path, old_paper=False)

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert (repo / "_site/paper/main.pdf").exists()
    assert json.loads((repo / "_site/paper/preview.json").read_text()) == {
        "changed": True,
        "diff": False,
        "new": True,
    }


def test_paper_preview_rejects_unresolved_citations(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    env["FAKE_BIBTEX_LOG"] = 'Warning--I didn\'t find a database entry for "missing"'

    result = subprocess.run(
        ["bash", str(SCRIPT)], cwd=repo, env=env, capture_output=True, text=True
    )

    assert result.returncode != 0
    assert "Unresolved paper citations" in result.stdout
    assert not (repo / "_site/paper/main.pdf").exists()


def test_paper_preview_rejects_undefined_citation_in_latex_log(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    env["FAKE_LATEX_LOG"] = "LaTeX Warning: Citation `missing' on page 1 undefined"

    result = subprocess.run(
        ["bash", str(SCRIPT)], cwd=repo, env=env, capture_output=True, text=True
    )

    assert result.returncode != 0
    assert not (repo / "_site/paper/main.pdf").exists()


def test_paper_preview_publishes_arxiv_bibliography(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    env["FAKE_BBL"] = r"\begin{thebibliography}{1}"

    run("bash", str(SCRIPT), cwd=repo, env=env)

    assert (repo / "_site/paper/main.bbl").read_text().strip() == env["FAKE_BBL"]


def test_unchanged_paper_has_no_diff_manifest(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert (repo / "_site/paper/main.pdf").exists()
    assert not (repo / "_site/paper/preview.json").exists()


def test_missing_comparison_base_still_builds_current_pdf(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)

    run("bash", str(SCRIPT), "", cwd=repo, env=env)

    assert (repo / "_site/paper/main.pdf").exists()
    assert not (repo / "_site/paper/preview.json").exists()


def test_missing_recorder_keeps_current_pdf_without_failing_build(tmp_path):
    repo, base, env, bin_dir = paper_repo(tmp_path)
    with (bin_dir / "latexmk").open("a") as mock:
        mock.write("rm -f build/main.fls\n")

    result = run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert "Could not compare paper versions" in result.stdout
    assert (repo / "_site/paper/main.pdf").exists()
    assert json.loads((repo / "_site/paper/preview.json").read_text()) == {
        "changed": True,
        "diff": False,
    }


def test_missing_git_base_keeps_current_pdf_without_failing_build(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)

    result = run("bash", str(SCRIPT), "missing-base", cwd=repo, env=env)

    assert "Could not compare paper versions" in result.stdout
    assert (repo / "_site/paper/main.pdf").exists()
    assert json.loads((repo / "_site/paper/preview.json").read_text())["diff"] is False


def test_latexdiff_failure_keeps_current_pdf(tmp_path):
    repo, base, env, bin_dir = paper_repo(tmp_path)
    (bin_dir / "latexdiff").write_text("#!/bin/bash\nexit 1\n")

    result = run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert "Could not build latexdiff PDF" in result.stdout
    assert (repo / "_site/paper/main.pdf").exists()
    assert json.loads((repo / "_site/paper/preview.json").read_text()) == {
        "changed": True,
        "diff": False,
        "other_inputs": False,
    }


def test_thumbnail_failure_keeps_diff_pdf(tmp_path):
    repo, base, env, bin_dir = paper_repo(tmp_path)
    (bin_dir / "pdftoppm").write_text("#!/bin/bash\nexit 1\n")

    result = run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert "Could not render paper diff thumbnails" in result.stdout
    assert (repo / "_site/paper/what-changed.pdf").exists()
    assert not list((repo / "_site/paper").glob("diff-page-*.png"))
    assert json.loads((repo / "_site/paper/preview.json").read_text()) == {
        "changed": True,
        "diff": True,
        "other_inputs": False,
        "thumbnail_limit": 12,
    }


def test_diff_records_actual_page_count_for_thumbnail_note(tmp_path):
    repo, base, env, bin_dir = paper_repo(tmp_path)
    (bin_dir / "pdfinfo").write_text("#!/bin/sh\necho 'Pages: 13'\n")
    (bin_dir / "pdfinfo").chmod(0o755)

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert (
        json.loads((repo / "_site/paper/preview.json").read_text())["page_count"] == 13
    )


def test_diff_does_not_delete_a_tracked_paper_file(tmp_path):
    repo, base, env, _ = paper_repo(tmp_path)
    tracked = repo / "paper/what-changed.tex"
    tracked.write_text("keep this file")
    run("git", "add", "paper/what-changed.tex", cwd=repo)
    run("git", "commit", "-qm", "add tracked file", cwd=repo)

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert tracked.read_text() == "keep this file"
    assert not list((repo / "paper").glob("what-changed.*.tex"))


def test_unread_paper_file_does_not_claim_paper_changed(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    (repo / "paper/README.md").write_text("new notes")
    run("git", "add", "paper/README.md", cwd=repo)
    run("git", "commit", "-qm", "add paper notes", cwd=repo)

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert not (repo / "_site/paper/preview.json").exists()


def test_changed_included_subdirectory_tex_builds_diff(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    subdir = repo / "paper/sections"
    subdir.mkdir()
    section = subdir / "intro.tex"
    section.write_text("old")
    run("git", "add", "paper/sections/intro.tex", cwd=repo)
    run("git", "commit", "-qm", "add section", cwd=repo)
    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    section.write_text("new")
    run("git", "commit", "-qam", "edit section", cwd=repo)
    env["FAKE_LATEX_INPUT"] = "sections/intro.tex"

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert (repo / "_site/paper/what-changed.pdf").exists()
    assert json.loads((repo / "_site/paper/preview.json").read_text())["diff"] is True


def test_root_level_tex_input_is_detected_without_false_diff_highlights(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    (repo / "shared.tex").write_text("old")
    run("git", "add", "shared.tex", cwd=repo)
    run("git", "commit", "-qm", "add shared input", cwd=repo)
    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    (repo / "shared.tex").write_text("new")
    run("git", "commit", "-qam", "edit shared input", cwd=repo)
    env["FAKE_LATEX_INPUT"] = "../shared.tex"

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert (repo / "_site/paper/main.pdf").exists()
    assert not (repo / "_site/paper/what-changed.pdf").exists()
    assert json.loads((repo / "_site/paper/preview.json").read_text()) == {
        "changed": True,
        "diff": False,
        "other_inputs": True,
    }


def test_bibliography_only_edit_links_unmarked_current_pdf(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    (repo / "references.bib").write_text("old")
    run("git", "add", "references.bib", cwd=repo)
    run("git", "commit", "-qm", "add bibliography", cwd=repo)
    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    (repo / "references.bib").write_text("new")
    run("git", "commit", "-qam", "edit bibliography", cwd=repo)
    env["FAKE_LATEX_DEPS"] = "../references.bib"

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert (repo / "_site/paper/main.pdf").exists()
    assert not (repo / "_site/paper/what-changed.pdf").exists()
    assert json.loads((repo / "_site/paper/preview.json").read_text()) == {
        "changed": True,
        "diff": False,
        "other_inputs": True,
    }


def test_unused_bibliography_edit_does_not_mark_paper_changed(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    (repo / "unused.bib").write_text("old")
    run("git", "add", "unused.bib", cwd=repo)
    run("git", "commit", "-qm", "add unused bibliography", cwd=repo)
    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    (repo / "unused.bib").write_text("new")
    run("git", "commit", "-qam", "edit unused bibliography", cwd=repo)

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert not (repo / "_site/paper/preview.json").exists()


def test_dependency_comment_does_not_mark_unused_bibliography_changed(tmp_path):
    repo, _, env, bin_dir = paper_repo(tmp_path)
    (repo / "unused.bib").write_text("old")
    run("git", "add", "unused.bib", cwd=repo)
    run("git", "commit", "-qm", "add unused bibliography", cwd=repo)
    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    (repo / "unused.bib").write_text("new")
    run("git", "commit", "-qam", "edit unused bibliography", cwd=repo)
    with (bin_dir / "latexmk").open("a") as mock:
        mock.write('sed -i "1i# Header: ../unused.bib" build/main.dep\n')

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert not (repo / "_site/paper/preview.json").exists()


def test_latexmkrc_change_is_a_paper_input(tmp_path):
    repo, _, env, _ = paper_repo(tmp_path)
    (repo / "paper/.latexmkrc").write_text("old")
    run("git", "add", "paper/.latexmkrc", cwd=repo)
    run("git", "commit", "-qm", "add configuration", cwd=repo)
    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    (repo / "paper/.latexmkrc").write_text("new")
    run("git", "commit", "-qam", "edit configuration", cwd=repo)

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert json.loads((repo / "_site/paper/preview.json").read_text()) == {
        "changed": True,
        "diff": False,
        "other_inputs": True,
    }


def test_preamble_only_edit_links_pdf_without_highlights(tmp_path):
    repo, base, env, bin_dir = paper_repo(tmp_path)
    (bin_dir / "latexdiff").write_text(
        "#!/bin/bash\nprintf '\\\\usepackage{new}\\n\\\\begin{document}\\nbody\\n'\n"
    )

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert not (repo / "_site/paper/what-changed.pdf").exists()
    assert json.loads((repo / "_site/paper/preview.json").read_text()) == {
        "changed": True,
        "diff": False,
        "other_inputs": False,
        "unhighlighted": True,
    }
