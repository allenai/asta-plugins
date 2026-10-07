"""Stop the smoke test's preview process group before removing its project."""

import os
import signal
import subprocess


def stop_preview(process: subprocess.Popen, timeout: float = 5) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        pass
    finally:
        # The shell can exit before Quarto; finish descendants even after wait succeeds.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=timeout)
