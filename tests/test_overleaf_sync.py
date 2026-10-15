"""Scheduler behavior over real workspace and Overleaf Git repositories."""

import importlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from asta.cli import cli
from tests.test_workspace_overleaf import URL, commit_all, git, overleaf_edit, run
from tests.test_workspace_overleaf import setup as setup  # noqa: F401

sync = importlib.import_module("asta.commands.overleaf_sync")


@pytest.fixture
def github(monkeypatch):
    state = {"prs": [], "issues": [], "merges": [], "writes": 0, "calls": []}

    def gh(root, *args, payload=None):
        state["calls"].append((args, payload))
        if state.get("fail_report") and args[0] == "api":
            raise sync.ov.SyncError("fixture reporting failure")
        if args[:2] == ("repo", "view"):
            return {
                "nameWithOwner": "allenai/test",
                "defaultBranchRef": {"name": "main"},
            }
        if args[:2] == ("label", "create"):
            return None
        if args[:2] == ("pr", "list"):
            for pr in state["prs"]:
                pr["headRefOid"] = git(
                    root, "ls-remote", "origin", "refs/heads/asta/overleaf-sync/1234567"
                ).split()[0]
            return state["prs"]
        if args[:2] == ("pr", "view"):
            return state["prs"][0]
        if args[:2] == ("pr", "merge"):
            state["merges"].append(args)
            if not state.get("allow_merge"):
                raise AssertionError("merge was not expected")
            git(root, "fetch", "origin", "main", "asta/overleaf-sync/1234567")
            with sync.tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / "merge"
                git(root, "clone", str(root.parent / "workspace.git"), str(dest))
                git(dest, "merge", "--squash", "origin/asta/overleaf-sync/1234567")
                bodyfile = args[args.index("--body-file") + 1]
                git(
                    dest,
                    "commit",
                    "-m",
                    "Sync Overleaf paper\n\n" + Path(bodyfile).read_text(),
                )
                git(dest, "push", "origin", "HEAD:main")
            state["prs"].clear()
            return None
        if args[0] == "api":
            if payload is None and "/issues?" in args[1]:
                return state["issues"]
            state["writes"] += 1
            if args[1].endswith("/pulls"):
                if state.pop("fail_create", False):
                    raise sync.ov.SyncError("fixture PR creation failure")
                pr = {
                    "number": 1,
                    "url": "https://github.com/allenai/test/pull/1",
                    "body": payload["body"],
                    "baseRefName": "main",
                    "labels": [],
                    "headRefOid": git(
                        root,
                        "ls-remote",
                        "origin",
                        "refs/heads/asta/overleaf-sync/1234567",
                    ).split()[0],
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "statusCheckRollup": [],
                }
                state["prs"].append(pr)
                return pr
            if args[1].endswith("/labels"):
                if state.pop("fail_label", False):
                    raise sync.ov.SyncError("fixture labeling failure")
                state["prs"][0]["labels"] = [{"name": sync.LABEL}]
            elif "/pulls/" in args[1]:
                state["prs"][0]["body"] = payload["body"]
            elif args[1].endswith("/issues"):
                state["issues"].append({**payload, "number": 2})
            elif "/issues/2" in args[1]:
                state["issues"][0].update(payload)
            return None
        raise AssertionError(args)

    monkeypatch.setattr(sync, "gh", gh)
    return state


def invoke(project):
    return CliRunner().invoke(
        cli, ["workspace", "overleaf", "sync", "--project", str(project)]
    )


def prepare(setup):
    seed, project = setup
    assert run(project, "pull", URL).exit_code == 0
    commit_all(project)
    git(project, "config", "user.name", "t")
    git(project, "config", "user.email", "t@t")
    git(project, "push", "origin", "HEAD:main")
    return seed, project


def test_new_edits_create_one_pr_and_quiet_rerun_waits_for_checks(setup, github):
    seed, project = prepare(setup)
    original = git(project, "rev-parse", "HEAD")
    overleaf_edit(seed, "main.tex", "coauthor edit\n")
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert len(github["prs"]) == 1
    assert not github["merges"]
    assert git(project, "rev-parse", "HEAD") == original
    assert git(project, "status", "--porcelain") == ""
    head = git(
        project, "ls-remote", "origin", "refs/heads/asta/overleaf-sync/1234567"
    ).split()[0]
    git(project, "fetch", "origin", head)
    assert "Co-authored-by: t <t@t>" in git(project, "show", "-s", "--format=%B", head)
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert len(github["prs"]) == 1
    assert not github["merges"]
    writes = github["writes"]
    assert invoke(project).exit_code == 0
    assert github["writes"] == writes  # unchanged waiting status does not repeat


def test_conflict_is_left_in_pr_and_never_merged(setup, github):
    seed, project = prepare(setup)
    (project / "paper/main.tex").write_text("workspace edit\n")
    commit_all(project)
    git(project, "push", "origin", "HEAD:main")
    overleaf_edit(seed, "main.tex", "Overleaf edit\n")
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert len(github["prs"]) == 1
    assert "author must resolve" in github["prs"][0]["body"]
    assert not github["merges"]
    assert not git(
        project, "ls-remote", "origin", "refs/asta/overleaf-sync-lock/1234567"
    )


def test_remote_lock_excludes_second_clone_and_releases_after_failure(setup):
    _, project = prepare(setup)
    with pytest.raises(RuntimeError):
        with sync.lock(project, "1234567") as acquired:
            assert acquired
            with sync.lock(project, "1234567") as second:
                assert not second
            raise RuntimeError("interrupted")
    with sync.lock(project, "1234567") as acquired:
        assert acquired


@pytest.mark.parametrize(
    "checks,expected",
    [
        ([], False),
        ([{"state": "PENDING"}], False),
        ([{"state": "FAILURE"}], False),
        ([{"state": "SUCCESS"}], True),
        (
            [{"state": "SUCCESS"}, {"status": "COMPLETED", "conclusion": "SKIPPED"}],
            True,
        ),
        (
            [{"state": "SUCCESS"}, {"status": "COMPLETED", "conclusion": "SUCCESS"}],
            True,
        ),
        (
            [{"state": "FAILURE"}, {"status": "COMPLETED", "conclusion": "SUCCESS"}],
            False,
        ),
        ([{"state": "SUCCESS"}, {"status": "IN_PROGRESS", "conclusion": ""}], False),
        ([{"status": "IN_PROGRESS", "conclusion": ""}], False),
        ([{"status": "COMPLETED", "conclusion": "FAILURE"}], False),
        ([{"status": "COMPLETED", "conclusion": "SKIPPED"}], False),
    ],
)
def test_checks_fail_closed(checks, expected):
    assert sync.checks_pass({"statusCheckRollup": checks}) == expected


@pytest.mark.parametrize("marker", ["<<<<<<< workspace", "=======", ">>>>>>> overleaf"])
def test_shared_check_refuses_paper_markers_before_render(tmp_path, marker):
    git(tmp_path, "init", "-b", "main")
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "overleaf.json").write_text(json.dumps({"url": URL, "base": "0" * 40}))
    (paper / "main.tex").write_text(marker + "\n")
    git(tmp_path, "add", "paper/overleaf.json", "paper/main.tex")
    script = (
        Path(__file__).parents[1]
        / "plugins/asta-tools/skills/workspace/assets/quarto-check.sh"
    )
    result = subprocess.run(
        ["sh", str(script)], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "conflict markers" in result.stdout
    assert "quarto" not in result.stderr


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
def test_quiet_checked_pr_squashes_with_credit_then_reruns_without_new_pr(
    setup, github
):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "invited author content\n")
    assert invoke(project).exit_code == 0
    github["allow_merge"] = True
    github["prs"][0]["statusCheckRollup"] = [{"state": "SUCCESS"}]
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert len(github["merges"]) == 1
    assert not github["prs"]
    git(project, "fetch", "origin", "main")
    assert "Co-authored-by: t <t@t>" in git(
        project, "show", "-s", "--format=%B", "FETCH_HEAD"
    )
    assert git(project, "show", "FETCH_HEAD:paper/main.tex") == "invited author content"
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert not github["prs"]


def test_published_metadata_only_pull_does_not_create_sync_pr(setup, github):
    seed, project = prepare(setup)
    (project / "paper/main.tex").write_text("published workspace text\n")
    commit_all(project)
    result = run(project, "publish")
    assert result.exit_code == 0, result.output
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert not github["prs"]
    assert not github["merges"]


def test_new_edit_defers_a_previously_checked_pr(setup, github):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "first edit\n")
    assert invoke(project).exit_code == 0
    github["prs"][0]["statusCheckRollup"] = [{"state": "SUCCESS"}]
    old = github["prs"][0]["headRefOid"]
    overleaf_edit(seed, "main.tex", "second edit\n")
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert not github["merges"]
    assert (
        git(
            project, "ls-remote", "origin", "refs/heads/asta/overleaf-sync/1234567"
        ).split()[0]
        != old
    )


@pytest.mark.parametrize("setup", ["sha1", "sha256"], indirect=True)
def test_publish_failure_after_merge_opens_deduplicated_issue(
    setup, github, monkeypatch
):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "ready to merge\n")
    assert invoke(project).exit_code == 0
    github["allow_merge"] = True
    github["prs"][0]["statusCheckRollup"] = [{"state": "SUCCESS"}]

    def fail_publish(*args, **kwargs):
        raise sync.ov.SyncError("fixture publication race")

    monkeypatch.setattr(sync.ov.publish, "callback", fail_publish)
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert "fixture publication race" in result.output
    assert len(github["merges"]) == 1
    assert not github["prs"]
    assert len(github["issues"]) == 1
    assert "fixture publication race" in github["issues"][0]["body"]
    writes = github["writes"]
    assert invoke(project).exit_code == 1
    assert len(github["issues"]) == 1
    assert github["writes"] == writes


def test_failed_label_is_repaired_on_next_run(setup, github):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "new edit\n")
    github["fail_label"] = True
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert len(github["prs"]) == 1
    assert github["prs"][0]["labels"] == []
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert len(github["prs"]) == 1
    assert github["prs"][0]["labels"] == [{"name": sync.LABEL}]


@pytest.mark.parametrize("merge_state", ["CLEAN", "BEHIND"])
def test_unrelated_default_edit_does_not_starve_checked_pr(setup, github, merge_state):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "ready paper\n")
    assert invoke(project).exit_code == 0
    pr = github["prs"][0]
    old = pr["headRefOid"]
    (project / "notes.txt").write_text("unrelated default content\n")
    commit_all(project)
    git(project, "push", "origin", "HEAD:main")
    pr["statusCheckRollup"] = [{"state": "SUCCESS"}]
    pr["mergeStateStatus"] = merge_state
    github["allow_merge"] = True
    result = invoke(project)
    assert result.exit_code == 0, result.output
    if merge_state == "CLEAN":
        assert len(github["merges"]) == 1
        git(project, "fetch", "origin", "main")
        assert (
            git(project, "show", "FETCH_HEAD:notes.txt") == "unrelated default content"
        )
    else:
        assert not github["merges"]
        assert (
            git(
                project, "ls-remote", "origin", "refs/heads/asta/overleaf-sync/1234567"
            ).split()[0]
            != old
        )


def test_pull_conflict_names_changed_file_commit_not_unrelated_paper_edit(
    setup, github
):
    seed, project = prepare(setup)
    (project / "paper/main.tex").write_text("workspace conflict\n")
    commit_all(project)
    culprit = git(project, "rev-parse", "HEAD")
    (project / "paper/old.tex").write_text("unrelated later paper edit\n")
    commit_all(project)
    unrelated = git(project, "rev-parse", "HEAD")
    git(project, "push", "origin", "HEAD:main")
    overleaf_edit(seed, "main.tex", "Overleaf conflict\n")
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert culprit in github["prs"][0]["body"]
    assert unrelated not in github["prs"][0]["body"]
    assert "paper/main.tex" in github["prs"][0]["body"]


def test_base_merge_conflict_names_changed_file_commit_not_default_tip(setup, github):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "Overleaf conflict\n")
    assert invoke(project).exit_code == 0
    (project / "paper/main.tex").write_text("workspace conflict\n")
    commit_all(project)
    culprit = git(project, "rev-parse", "HEAD")
    (project / "notes.txt").write_text("unrelated last commit\n")
    commit_all(project)
    unrelated = git(project, "rev-parse", "HEAD")
    git(project, "push", "origin", "HEAD:main")
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert culprit in github["prs"][0]["body"]
    assert unrelated not in github["prs"][0]["body"]


@pytest.mark.parametrize("filename", ["latexmkrc", ".latexmkrc"])
def test_build_configuration_is_left_for_human_merge(setup, github, filename):
    seed, project = prepare(setup)
    overleaf_edit(seed, filename, "$pdflatex = 'echo changed';\n")
    assert invoke(project).exit_code == 0
    github["prs"][0]["statusCheckRollup"] = [{"state": "SUCCESS"}]
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert "person must review and merge" in github["prs"][0]["body"]
    assert not github["merges"]
    writes = github["writes"]
    assert invoke(project).exit_code == 1
    assert github["writes"] == writes


def test_held_lock_is_nonzero_and_reported_once(setup, github):
    _, project = prepare(setup)
    with sync.lock(project, "1234567") as acquired:
        assert acquired
        result = invoke(project)
        assert result.exit_code == 1, result.output
        assert "lock is held" in result.output
        assert len(github["issues"]) == 1
        writes = github["writes"]
        assert invoke(project).exit_code == 1
        assert github["writes"] == writes


def test_successful_update_clears_stale_failure_status(setup, github):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "first edit\n")
    assert invoke(project).exit_code == 0
    sync.report(
        project, "allenai/test", "1234567", "old conflict refusal", github["prs"][0]
    )
    overleaf_edit(seed, "main.tex", "second edit\n")
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert github["prs"][0]["body"] == sync.DEFAULT_BODY


def test_lock_release_error_preserves_original_failure(setup, monkeypatch):
    _, project = prepare(setup)
    original = sync.ov.git

    def fail_release(*args, **kwargs):
        if args[0] == "push" and ":refs/asta/overleaf-sync-lock/1234567" in args:
            raise sync.ov.SyncError("fixture release failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(sync.ov, "git", fail_release)
    with pytest.raises(RuntimeError, match="original failure"):
        with sync.lock(project, "1234567") as acquired:
            assert acquired
            raise RuntimeError("original failure")


def test_reporting_error_preserves_original_refusal(setup, github, monkeypatch):
    _, project = prepare(setup)

    def fail_pull(*args, **kwargs):
        github["fail_report"] = True
        raise sync.ov.SyncError("original pull failure")

    monkeypatch.setattr(sync, "pull_into", fail_pull)
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert "original pull failure" in result.output
    assert "fixture reporting failure" not in result.output


def test_missing_branch_configuration_reports_refusal(setup, github, tmp_path):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "new edit\n")
    assert invoke(project).exit_code == 0
    dest = tmp_path / "human"
    git(project, "clone", str(project.parent / "workspace.git"), str(dest))
    git(dest, "checkout", "asta/overleaf-sync/1234567")
    git(dest, "rm", "paper/overleaf.json")
    git(dest, "commit", "-m", "remove config")
    git(dest, "push", "origin", "HEAD:asta/overleaf-sync/1234567")
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert "restore the linked paper configuration" in result.output
    assert "restore the linked paper configuration" in github["prs"][0]["body"]


@pytest.mark.parametrize("key", ["user.name", "user.email"])
def test_missing_identity_is_explicit_and_reported(setup, github, monkeypatch, key):
    _, project = prepare(setup)
    git(project, "config", "--unset", key)
    monkeypatch.delenv("GIT_AUTHOR_NAME", raising=False)
    monkeypatch.delenv("GIT_AUTHOR_EMAIL", raising=False)
    monkeypatch.delenv("GIT_COMMITTER_NAME", raising=False)
    monkeypatch.delenv("GIT_COMMITTER_EMAIL", raising=False)
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert f"Configure Git {key}" in result.output
    assert len(github["issues"]) == 1
    assert not git(
        project, "ls-remote", "origin", "refs/asta/overleaf-sync-lock/1234567"
    )


def test_sync_rejects_root_and_sibling_paths(setup, github, monkeypatch, tmp_path):
    seed, project = prepare(setup)
    result = CliRunner().invoke(
        cli, ["workspace", "overleaf", "sync", "--project", str(project), "--dir", "."]
    )
    assert result.exit_code == 1, result.output
    assert not github["prs"]
    overleaf_edit(seed, "main.tex", "new edit\n")
    assert invoke(project).exit_code == 0
    dest = tmp_path / "human"
    git(project, "clone", str(project.parent / "workspace.git"), str(dest))
    git(dest, "checkout", "asta/overleaf-sync/1234567")
    (dest / "paper2").mkdir()
    (dest / "paper2/notes.tex").write_text("outside paper\n")
    commit_all(dest)
    git(dest, "push", "origin", "HEAD:asta/overleaf-sync/1234567")
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert "outside the paper" in result.output
    assert not github["merges"]


@pytest.mark.parametrize(
    "filename,data,blocked",
    [
        ("main.tex", b"<<<<<<<\r\n", True),
        ("main.tex", b"=======\r\n", True),
        ("main.tex", b">>>>>>>\r\n", True),
        ("main.tex", b"|||||||\r\n", True),
        ("main.tex", b">>>>>>> overleaf\r\n", True),
        ("notes.md", b"Heading\n=======\n", False),
        ("notes.md", b"<<<<<<< workspace\n", True),
        ("image.pdf", b"<<<<<<< workspace\n", False),
        ("main.tex", b"\0<<<<<<< workspace\n", False),
    ],
)
def test_marker_checks_agree_for_crlf_markdown_and_assets(
    tmp_path, filename, data, blocked
):
    git(tmp_path, "init", "-b", "main")
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "overleaf.json").write_text(json.dumps({"url": URL, "base": "0" * 40}))
    (paper / filename).write_bytes(data)
    git(tmp_path, "add", "paper/overleaf.json", "paper/" + filename)
    git(tmp_path, "commit", "-m", "fixture")
    assert bool(sync.conflict_files(tmp_path, "paper/")) == blocked
    script = (
        Path(__file__).parents[1]
        / "plugins/asta-tools/skills/workspace/assets/quarto-check.sh"
    )
    result = subprocess.run(
        ["sh", str(script)], cwd=tmp_path, capture_output=True, text=True
    )
    assert ("Unresolved paper conflict markers" in result.stdout) == blocked


def test_shared_check_outside_git_has_no_traceback(tmp_path):
    script = (
        Path(__file__).parents[1]
        / "plugins/asta-tools/skills/workspace/assets/quarto-check.sh"
    )
    result = subprocess.run(
        ["sh", str(script)], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "Git checkout" in result.stdout
    assert "Traceback" not in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX byte filenames")
def test_shared_check_handles_non_utf8_paths(tmp_path):
    git(tmp_path, "init", "-b", "main")
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "overleaf.json").write_text("{}")
    name = os.fsencode(paper) + b"/odd-\xff.tex"
    with open(name, "wb") as stream:
        stream.write(b"=======\r\n")
    git(tmp_path, "add", "--", "paper")
    script = (
        Path(__file__).parents[1]
        / "plugins/asta-tools/skills/workspace/assets/quarto-check.sh"
    )
    result = subprocess.run(["sh", str(script)], cwd=tmp_path, capture_output=True)
    assert result.returncode == 1
    assert b"conflict markers" in result.stdout
    assert b"Traceback" not in result.stderr


BRANCH = "refs/heads/asta/overleaf-sync/1234567"
SCRIPT = (
    Path(__file__).parents[1]
    / "plugins/asta-tools/skills/workspace/assets/quarto-check.sh"
)


def test_held_lock_reports_on_open_sync_pr(setup, github):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "new edit\n")
    assert invoke(project).exit_code == 0
    with sync.lock(project, "1234567") as acquired:
        assert acquired
        result = invoke(project)
    assert result.exit_code == 1, result.output
    assert "lock is held" in github["prs"][0]["body"]
    assert github["issues"] == []


def test_branch_pushed_before_pr_creation_is_recovered(setup, github):
    seed, project = prepare(setup)
    overleaf_edit(seed, "main.tex", "new edit\n")
    github["fail_create"] = True
    assert invoke(project).exit_code == 1
    assert git(project, "ls-remote", "origin", BRANCH)
    result = invoke(project)
    assert result.exit_code == 0, result.output
    assert len(github["prs"]) == 1


def test_unowned_reserved_branch_without_pr_is_not_replaced(setup, github):
    seed, project = prepare(setup)
    (project / "paper/notes.tex").write_text("someone's work\n")
    git(project, "add", "--", "paper/notes.tex")
    git(project, "commit", "-m", "Draft notes")
    git(project, "push", "origin", f"HEAD:{BRANCH}")
    theirs = git(project, "rev-parse", "HEAD")
    overleaf_edit(seed, "main.tex", "new edit\n")
    result = invoke(project)
    assert result.exit_code == 1, result.output
    assert "sync did not create" in result.output
    assert git(project, "ls-remote", "origin", BRANCH).split()[0] == theirs
    assert github["prs"] == [] and len(github["issues"]) == 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
@pytest.mark.parametrize("linked", ["file", "directory"])
def test_shared_check_never_follows_symlinks_out_of_checkout(tmp_path, linked):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "main.tex").write_bytes(b"<<<<<<< HEAD\n")
    repo = tmp_path / "repo"
    paper = repo / "paper"
    (paper / "sub").mkdir(parents=True)
    git(repo, "init", "-b", "main")
    (paper / "overleaf.json").write_text("{}")
    if linked == "file":
        (paper / "main.tex").symlink_to(outside / "main.tex")
    else:
        (paper / "sub/main.tex").write_text("clean\n")
    git(repo, "add", "--", "paper")
    if linked == "directory":
        (paper / "sub/main.tex").unlink()
        (paper / "sub").rmdir()
        (paper / "sub").symlink_to(outside)
    result = subprocess.run(
        ["sh", str(SCRIPT)], cwd=repo, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "not symlinks" in result.stdout
    assert "conflict markers" not in result.stdout


def test_shared_check_streams_long_lines(tmp_path):
    git(tmp_path, "init", "-b", "main")
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "overleaf.json").write_text("{}")
    (paper / "main.tex").write_bytes(b"x" * 200_000 + b"<<<<<<< not a line start\n")
    (paper / "refs.bib").write_bytes(b"y" * 200_000 + b"\n>>>>>>> theirs\n")
    git(tmp_path, "add", "--", "paper")
    result = subprocess.run(
        ["sh", str(SCRIPT)], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "paper/refs.bib" in result.stdout
    assert "paper/main.tex" not in result.stdout
