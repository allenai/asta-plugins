"""Smoke cleanup stops descendants even when the launch shell exits first."""

import importlib.util
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "posix", reason="requires process groups")
def test_cleanup_stops_child_that_ignores_sigterm(tmp_path):
    path = Path(__file__).parent / "fixtures/devcontainer-smoke/preview_process.py"
    spec = importlib.util.spec_from_file_location("preview_process", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ready = tmp_path / "ready"
    stopped = tmp_path / "stopped"
    child = (
        "import signal,time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"Path({str(ready)!r}).touch(); "
        f"signal.signal(signal.SIGUSR1, lambda *_: Path({str(stopped)!r}).touch()); "
        "time.sleep(60)"
    )
    parent = (
        "import subprocess,sys; "
        "p=subprocess.Popen([sys.executable, '-c', sys.argv[1]]); "
        "print(p.pid, flush=True); p.wait()"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", parent, child],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        child_pid = int(process.stdout.readline())
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), "descendant did not install its signal handlers"
        module.stop_preview(process)
        try:
            os.kill(child_pid, signal.SIGUSR1)
        except ProcessLookupError:
            pass
        time.sleep(0.1)
        assert not stopped.exists(), "descendant survived cleanup"
        assert process.returncode is not None
    finally:
        module.stop_preview(process)
        process.stdout.close()
