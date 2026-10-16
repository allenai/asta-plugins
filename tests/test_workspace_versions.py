"""Workspace sync explains a mismatch between the installed asta and the pin."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from asta import __version__
from asta.cli import cli
from asta.commands import workspace as workspace_module
from asta.commands import workspace_versions
from tests.test_workspace_sync import _archive, project_with_ref

RULES = Path(__file__).parents[1] / workspace_module.ASSET


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("v0.113.0", (0, 113, 0)),
        ("0.113.0", (0, 113, 0)),
        ("main", None),
        ("v0.113.0-rc1", None),
        ("0.114.0.dev0", None),
        ("a" * 40, None),
    ],
)
def test_release_accepts_only_final_releases(text, expected) -> None:
    assert workspace_versions.release(text) == expected


def _sync(project: Path, monkeypatch, cli_version, rules=b"rule\n", *extra):
    calls = []

    def fetch(repository, ref):
        calls.append(ref)
        return rules, _archive({})

    monkeypatch.setattr(workspace_module, "load_asset", fetch)
    monkeypatch.setattr(workspace_versions, "installed", lambda: cli_version)
    args = ["workspace", "sync", "--project", str(project), *extra]
    return CliRunner().invoke(cli, args), calls


def test_rules_needing_newer_cli_fail_with_update_command(
    tmp_path: Path, monkeypatch
) -> None:
    project = project_with_ref(tmp_path, "v0.120.0")
    rules = b"ASTA_WORKSPACE_MIN_CLI := 0.120.0\nrule\n"
    result, _ = _sync(project, monkeypatch, (0, 110, 0), rules)
    assert result.exit_code != 0
    assert "needs asta 0.120.0 or newer; this is asta 0.110.0" in result.output
    assert "uv tool install --force" in result.output
    assert "asta-plugins.git@v0.120.0" in result.output
    assert not (project / ".asta/cache/workspace.mk").exists()


def test_cached_rules_are_checked_against_the_running_cli(
    tmp_path: Path, monkeypatch
) -> None:
    project = project_with_ref(tmp_path, "v0.120.0")
    rules = b"ASTA_WORKSPACE_MIN_CLI := 0.120.0\nrule\n"
    result, _ = _sync(project, monkeypatch, (0, 120, 0), rules)
    assert result.exit_code == 0, result.output
    result, calls = _sync(project, monkeypatch, (0, 119, 0), rules)
    assert calls == []
    assert result.exit_code != 0
    assert "needs asta 0.120.0 or newer" in result.output


def test_rules_without_minimum_and_unknown_cli_are_accepted(
    tmp_path: Path, monkeypatch
) -> None:
    project = project_with_ref(tmp_path, "main")
    result, _ = _sync(project, monkeypatch, (0, 105, 0))
    assert result.exit_code == 0, result.output
    rules = b"ASTA_WORKSPACE_MIN_CLI := 0.120.0\nrule\n"
    result, _ = _sync(project, monkeypatch, None, rules, "--refresh")
    assert result.exit_code == 0, result.output


def test_pin_older_than_supported_rules_says_to_move_it(
    tmp_path: Path, monkeypatch
) -> None:
    project = project_with_ref(tmp_path, "v0.104.0")
    result, calls = _sync(project, monkeypatch, (0, 113, 0))
    assert result.exit_code != 0
    assert calls == []
    assert "this asta supports v0.105.0 or newer" in result.output
    assert "Move the pin in .github/workflows/docs.yml" in result.output


def test_newer_cli_than_pin_explains_how_to_move_it_without_changing_files(
    tmp_path: Path, monkeypatch
) -> None:
    project = project_with_ref(tmp_path, "v0.110.0")
    docs = project / ".github/workflows/docs.yml"
    before = docs.read_text()
    result, calls = _sync(project, monkeypatch, (0, 113, 0))
    assert result.exit_code == 0, result.output
    assert calls == ["v0.110.0"]
    assert "asta 0.113.0 is newer than the asta-plugins@v0.110.0" in result.output
    assert "change @v0.110.0 to @v0.113.0" in result.output
    assert docs.read_text() == before


@pytest.mark.parametrize(
    ("ref", "cli_version"),
    [("v0.113.0", (0, 113, 0)), ("main", (0, 113, 0)), ("v0.110.0", None)],
)
def test_no_pin_notice_without_a_newer_final_release(
    tmp_path: Path, monkeypatch, ref, cli_version
) -> None:
    project = project_with_ref(tmp_path, ref)
    result, _ = _sync(project, monkeypatch, cli_version)
    assert result.exit_code == 0, result.output
    assert "is newer than" not in result.output


def test_published_rules_load_with_this_release() -> None:
    needed = workspace_versions.rules_min_cli(RULES.read_bytes())
    assert needed is not None
    assert needed >= workspace_versions.OLDEST_RULES_REF
    assert needed <= workspace_versions.release(__version__)
