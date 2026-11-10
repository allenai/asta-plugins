"""CI's per-Python test jobs roll up into one check whose name never changes."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
JOBS = yaml.load(
    (ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader
)["jobs"]


def test_tests_ok_needs_every_per_python_job():
    per_python = {
        name
        for name, job in JOBS.items()
        if "python-version" in job.get("strategy", {}).get("matrix", {})
    }
    gate = JOBS["tests-ok"]
    needs = gate["needs"]
    assert per_python and per_python <= set(
        [needs] if isinstance(needs, str) else needs
    )
    assert gate["if"] == "always()"
    assert gate["steps"][-1]["env"]["RESULT"] == "${{ needs.test.result }}"


def test_code_quality_runs_on_x86_for_every_build_runner():
    # The shellcheck action installs an x86_64 binary, so code-quality on the
    # release checks' arm build-runner fails before checking anything.
    assert JOBS["code-quality"]["runs-on"] == "ubuntu-latest"


@pytest.mark.parametrize("result", ["success", "failure", "cancelled", "skipped"])
def test_tests_ok_passes_only_on_success(result):
    step = JOBS["tests-ok"]["steps"][-1]
    run = subprocess.run(
        ["bash", "-c", step["run"]],
        env=dict(os.environ, RESULT=result),
        capture_output=True,
    )
    assert (run.returncode == 0) == (result == "success")
