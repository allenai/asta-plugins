import json
import os
import re
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from click.testing import CliRunner

from asta.commands import workspace as workspace_module
from asta.commands.workspace import workspace
from tests.workspace.test_workspace_what_changed import ASSETS, git


@pytest.mark.parametrize("directory", [".", "research workspace/docs"])
def test_template_with_real_quarto(tmp_path: Path, directory: str) -> None:
    source = os.environ.get(
        "ASTA_TEST_WORKSPACE_TEMPLATE",
        str(Path(__file__).resolve().parents[3] / "examples/workspace"),
    )
    assert shutil.which("make") and shutil.which("quarto")
    repository = tmp_path / "project"
    project = repository / directory
    project.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, project, ignore=shutil.ignore_patterns(".git"))
    repo = ASSETS.parents[4]
    ref = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    workflow = project / ".github/workflows/docs.yml"
    workflow.write_text(
        re.sub(
            r"(uses: allenai/asta-plugins/\.github/workflows/workspace-quarto-site\.yml@)\S+",
            rf"\g<1>{ref}",
            workflow.read_text(),
        )
    )
    files = subprocess.check_output(
        ["git", "-C", source, "ls-files"], text=True
    ).splitlines()
    git(repository, "init", "-q")
    git(project, "add", *files)
    git(repository, "commit", "-qm", "template baseline")
    git(repository, "tag", "last-read")
    with (project / "index.qmd").open("a") as page:
        page.write("\nA newly drafted paragraph for local comparison.\n")
    subprocess.run(["make", "render"], cwd=project, check=True)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    with workspace_module.preview_process(
        ["quarto", "preview", "--no-browser", "--port", str(port)],
        project,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    ) as live:
        try:
            deadline = time.monotonic() + 30
            while True:
                assert live.poll() is None, "Live Quarto preview exited"
                try:
                    with urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
                        assert response.status == 200
                        break
                except (URLError, TimeoutError):
                    assert time.monotonic() < deadline, "Live preview never started"
                    time.sleep(0.1)
            live_page = (project / "_site/index.html").read_bytes()
            for _ in range(2):
                result = CliRunner().invoke(
                    workspace, ["what-changed", "last-read", "--project", str(project)]
                )
                assert result.exit_code == 0, result.output
                report = (
                    project / ".asta/cache/what-changed/what-changed.html"
                ).read_text()
                assert re.search(r"<ins\b[^>]*>[^<]*newly drafted paragraph", report)
                assert "what-changed/what-changed.html" in result.stdout
                assert 'href="#what-changed-html"' not in report
                assert live.poll() is None
                assert (project / "_site/index.html").read_bytes() == live_page
        finally:
            workspace_module.stop_preview(live, signal.SIGTERM)
    manifest = json.loads((project / ".asta/cache/workspace.json").read_text())
    assert manifest["ref"] == ref
    assert "what-changed.py" in manifest["scripts"]
