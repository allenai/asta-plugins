"""SessionStart must not downgrade the CLI shared by different projects."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = (
    Path(__file__).resolve().parents[1] / "plugins/asta-tools/hooks/sync-cli-version.sh"
)


@pytest.mark.parametrize(
    ("installed", "version_status", "install"),
    [
        (None, 0, True),
        ("0.121.0", 0, True),
        ("0.9.99", 0, True),
        ("0.125.0", 0, False),
        ("0.125.1", 0, False),
        ("0.126.0", 0, False),
        ("0.1000.0", 0, False),
        ("1.0.0", 0, False),
        ("unknown", 0, False),
        ("", 1, True),
        ("unknown", 1, True),
        ("0.126.0", 1, True),
        ("0.121.0 (Python 3.12.1)", 0, True),
        ("0.126.0 (Python 3.12.1)", 0, False),
    ],
)
@pytest.mark.parametrize("install_status", [0, 1])
def test_sync_only_installs_missing_older_or_broken_cli(
    tmp_path, installed, version_status, install, install_status
):
    # Fix the hook's version so release bumps cannot change this regression case.
    hook = tmp_path / "sync-cli-version.sh"
    hook.write_text(
        re.sub(r"PLUGIN_VERSION=\S+", "PLUGIN_VERSION=0.125.0", HOOK.read_text())
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Isolate PATH, including from an actual installed asta/uv.
    for name in ("grep", "awk", "head"):
        executable = shutil.which(name)
        assert executable is not None, f"Required test executable is missing: {name}"
        (bin_dir / name).symlink_to(executable)
    if installed is not None:
        asta = bin_dir / "asta"
        asta.write_text(
            f"#!/bin/sh\necho 'asta, version {installed}'\nexit {version_status}\n"
        )
        asta.chmod(0o755)
    uv = bin_dir / "uv"
    uv.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$INSTALL_LOG"\nexit "$INSTALL_STATUS"\n'
    )
    uv.chmod(0o755)
    log = tmp_path / "install.log"
    result = subprocess.run(
        ["/bin/bash", str(hook)],
        env={
            "PATH": str(bin_dir),
            "INSTALL_LOG": str(log),
            "INSTALL_STATUS": str(install_status),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == (install_status if install else 0), result.stderr
    if install:
        force = "--force " if installed is not None else ""
        assert log.read_text().splitlines() == [
            f"tool install {force}git+https://github.com/allenai/asta-plugins.git@v0.125.0"
        ]
        if installed is not None and version_status == 0:
            assert f"from {installed.split()[0]} to 0.125.0" in result.stdout
    else:
        assert not log.exists()
