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


@pytest.mark.parametrize(
    ("older", "newer"),
    [
        ("0.106.0.dev0", "0.106.0a1"),
        ("0.106.0a1", "0.106.0rc1"),
        ("0.106.0rc1", "0.106.0"),
        ("0.106.0", "0.106.0.post1.dev0"),
        ("0.106.0.post1.dev0", "0.106.0.post1"),
        ("0.105.9.post3", "0.106.0.dev0"),
    ],
)
def test_cli_version_follows_pep_440(older, newer) -> None:
    assert workspace_versions.cli_version(older) < workspace_versions.cli_version(newer)


@pytest.mark.parametrize("text", ["0.106.0-rc1", "0.106.0.rc1", "0.106.0c1"])
def test_non_normalized_pre_releases_fail_the_minimum(text) -> None:
    rules = b"ASTA_WORKSPACE_MIN_CLI := 0.106.0\n"
    message = workspace_versions.cli_too_old(rules, "v0.106.0", text)
    assert message is not None and "needs asta 0.106.0 or newer" in message


def test_unreadable_cli_version_does_not_pass() -> None:
    rules = b"ASTA_WORKSPACE_MIN_CLI := 0.106.0\n"
    message = workspace_versions.cli_too_old(rules, "v0.106.0", "not-a-version")
    assert message is not None and "cannot read this asta's version" in message


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("v0.120.0", "@v0.120.0"),
        ("v0.100.0", "@v0.106.0"),
        ("main", "@main"),
        ("latest", "@latest"),
    ],
)
def test_update_command_suggests_the_pinned_release(ref, expected) -> None:
    rules = b"ASTA_WORKSPACE_MIN_CLI := 0.106.0\n"
    message = workspace_versions.cli_too_old(rules, ref, "0.105.0")
    assert message.endswith(f"asta-plugins.git{expected}")


def test_messages_name_the_source_only_when_given() -> None:
    rules = b"ASTA_WORKSPACE_MIN_CLI := 0.106.0\n"
    for message in (
        workspace_versions.cli_too_old(rules, "v0.106.0", "0.105.0"),
        workspace_versions.pin_too_old("v0.104.0"),
        workspace_versions.pin_behind("v0.106.0", "0.110.0"),
    ):
        assert message is not None and "docs.yml" not in message
    named = workspace_versions.pin_too_old("v0.104.0", "Makefile")
    assert "pin in Makefile" in named


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (b"ASTA_WORKSPACE_MIN_CLI := 0.120.0 # required", (0, 120, 0)),
        (b"ASTA_WORKSPACE_MIN_CLI ?= v0.120.0", (0, 120, 0)),
        (b"ASTA_WORKSPACE_MIN_CLI=0.120.0#note", (0, 120, 0)),
        (b"override ASTA_WORKSPACE_MIN_CLI := 0.120.0", (0, 120, 0)),
        (b"export ASTA_WORKSPACE_MIN_CLI := 0.120.0", (0, 120, 0)),
        (b"export override ASTA_WORKSPACE_MIN_CLI = 0.120.0", (0, 120, 0)),
        (
            b"ASTA_WORKSPACE_MIN_CLI := 0.106.0\nASTA_WORKSPACE_MIN_CLI := 0.120.0",
            (0, 120, 0),
        ),
    ],
)
def test_min_cli_declaration_allows_make_syntax(line, expected) -> None:
    assert workspace_versions.rules_min_cli(line + b"\nrule\n") == expected


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
    result, _ = _sync(project, monkeypatch, "0.110.0", rules)
    assert result.exit_code != 0
    assert "needs asta 0.120.0 or newer; this is asta 0.110.0" in result.output
    assert "uv tool install --force" in result.output
    assert "asta-plugins.git@v0.120.0" in result.output
    assert not (project / ".asta/cache/workspace.mk").exists()


@pytest.mark.parametrize("cli_version", ["0.105.0.dev0", "0.120.0rc1", "0.120.0.dev3"])
def test_prerelease_cli_below_minimum_fails(
    tmp_path: Path, monkeypatch, cli_version
) -> None:
    project = project_with_ref(tmp_path, "v0.120.0")
    rules = b"ASTA_WORKSPACE_MIN_CLI := 0.120.0 # required\nrule\n"
    result, _ = _sync(project, monkeypatch, cli_version, rules)
    assert result.exit_code != 0
    assert f"needs asta 0.120.0 or newer; this is asta {cli_version}" in result.output


def test_post_release_cli_meets_minimum(tmp_path: Path, monkeypatch) -> None:
    project = project_with_ref(tmp_path, "v0.120.0")
    rules = b"ASTA_WORKSPACE_MIN_CLI := 0.120.0\nrule\n"
    result, _ = _sync(project, monkeypatch, "0.120.0.post1", rules)
    assert result.exit_code == 0, result.output
    assert "is newer than" not in result.output


def test_unreadable_min_cli_declaration_fails(tmp_path: Path, monkeypatch) -> None:
    project = project_with_ref(tmp_path, "v0.120.0")
    rules = b"ASTA_WORKSPACE_MIN_CLI := next\nrule\n"
    result, _ = _sync(project, monkeypatch, "0.120.0", rules)
    assert result.exit_code != 0
    assert "unreadable ASTA_WORKSPACE_MIN_CLI := next" in result.output
    assert not (project / ".asta/cache/workspace.mk").exists()


def test_cached_rules_are_checked_against_the_running_cli(
    tmp_path: Path, monkeypatch
) -> None:
    project = project_with_ref(tmp_path, "v0.120.0")
    rules = b"ASTA_WORKSPACE_MIN_CLI := 0.120.0\nrule\n"
    result, _ = _sync(project, monkeypatch, "0.120.0", rules)
    assert result.exit_code == 0, result.output
    result, calls = _sync(project, monkeypatch, "0.119.0", rules)
    assert calls == []
    assert result.exit_code != 0
    assert "needs asta 0.120.0 or newer" in result.output


def test_rules_without_minimum_accepted_but_unknown_cli_is_not(
    tmp_path: Path, monkeypatch
) -> None:
    project = project_with_ref(tmp_path, "main")
    result, _ = _sync(project, monkeypatch, "0.105.0")
    assert result.exit_code == 0, result.output
    rules = b"ASTA_WORKSPACE_MIN_CLI := 0.120.0\nrule\n"
    result, _ = _sync(project, monkeypatch, None, rules, "--refresh")
    assert result.exit_code != 0
    assert "cannot read this asta's version." in result.output


def test_pin_older_than_supported_rules_says_to_move_it(
    tmp_path: Path, monkeypatch
) -> None:
    project = project_with_ref(tmp_path, "v0.104.0")
    result, calls = _sync(project, monkeypatch, "0.113.0")
    assert result.exit_code != 0
    assert calls == []
    assert "this asta supports v0.105.0 or newer" in result.output
    assert "Move the asta-plugins pin in .github/workflows/docs.yml" in result.output


def test_newer_cli_than_pin_explains_how_to_move_it_without_changing_files(
    tmp_path: Path, monkeypatch
) -> None:
    project = project_with_ref(tmp_path, "v0.110.0")
    docs = project / ".github/workflows/docs.yml"
    before = docs.read_text()
    result, calls = _sync(project, monkeypatch, "0.113.0")
    assert result.exit_code == 0, result.output
    assert calls == ["v0.110.0"]
    assert (
        "asta 0.113.0 is newer than the pinned asta-plugins@v0.110.0" in result.output
    )
    assert (
        "change @v0.110.0 to @v0.113.0 in .github/workflows/docs.yml" in result.output
    )
    assert docs.read_text() == before


@pytest.mark.parametrize(
    ("ref", "cli_version"),
    [("v0.113.0", "0.113.0"), ("main", "0.113.0"), ("v0.110.0", None)],
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
    assert workspace_versions.cli_version(__version__) >= workspace_versions.Version(
        workspace_versions.format_release(needed)
    )
