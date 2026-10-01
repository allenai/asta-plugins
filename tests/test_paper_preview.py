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
    return subprocess.run(args, cwd=cwd, env=env, check=True, capture_output=True, text=True)


def test_paper_preview_builds_current_and_diff_pdfs(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run("git", "init", "-q", cwd=repo)
    run("git", "config", "user.email", "test@example.invalid", cwd=repo)
    run("git", "config", "user.name", "Test", cwd=repo)
    (repo / "paper").mkdir()
    (repo / "paper/main.tex").write_text("old")
    run("git", "add", "paper/main.tex", cwd=repo)
    run("git", "commit", "-qm", "base", cwd=repo)
    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    (repo / "paper/main.tex").write_text("new")
    run("git", "commit", "-qam", "edit", cwd=repo)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    commands = {
        "latexmk": '#!/bin/bash\nmkdir -p build\nname="${@: -1}"\nprintf pdf > "build/${name%.tex}.pdf"\n',
        "latexdiff": "#!/bin/bash\nprintf 'diff source\\n'\n",
        "pdftoppm": '#!/bin/bash\nname="${@: -1}"\nprintf png > "${name}-1.png"\n',
    }
    for name, contents in commands.items():
        path = bin_dir / name
        path.write_text(contents)
        path.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    run("bash", str(SCRIPT), base, cwd=repo, env=env)

    assert (repo / "_site/paper/main.pdf").exists()
    assert (repo / "_site/paper/what-changed.pdf").exists()
    assert (repo / "_site/paper/diff-page-1.png").exists()
    assert json.loads((repo / "_site/paper/preview.json").read_text()) == {
        "changed": True,
        "diff": True,
    }
    assert not (repo / "paper/what-changed.tex").exists()
