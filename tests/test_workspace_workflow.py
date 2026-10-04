import importlib.util
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(".github/workflows/workspace-quarto-site.yml")
WORKSPACE_ASSETS = Path("plugins/asta-tools/skills/workspace/assets")


def _run_paper_step(tmp_path: Path, *, download_fails: bool = False):
    workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    step = next(
        item for item in workflow["jobs"]["build"]["steps"] if item.get("id") == "paper"
    )
    script = step["run"].replace("${{ job.workflow_repository }}", "owner/repo")
    script = script.replace("${{ job.workflow_sha }}", "source-commit")
    source = WORKSPACE_ASSETS / "paper-discovery.py"
    project = tmp_path / "project"
    paper = project / "paper"
    paper.mkdir(parents=True)
    (paper / "main.tex").write_text("paper")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(
        '#!/bin/sh\n[ "${FAIL_CURL:-0}" != 1 ] || exit 1\ncp "$DISCOVERY_SOURCE" "$4"\n'
    )
    curl.chmod(0o755)
    sudo = bin_dir / "sudo"
    sudo.write_text("#!/bin/sh\nexit 1\n")
    sudo.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "PR_BASE": "",
        "DISCOVERY_SOURCE": str(source.resolve()),
        "FAIL_CURL": "1" if download_fails else "0",
    }
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", script],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
    )
    return project, result


def test_paper_toolchain_failure_keeps_preview_diagnostic(tmp_path: Path) -> None:
    project, result = _run_paper_step(tmp_path)

    assert result.returncode != 0
    assert (
        project / "_site/paper-previews/paper/build-failed.txt"
    ).read_text().strip() == ("Could not update LaTeX package lists.")
    assert (
        project / "_site/paper-previews/paper/preview.json"
    ).read_text().strip() == ('{"changed":false}')


def test_paper_discovery_failure_keeps_site_diagnostic(tmp_path: Path) -> None:
    project, result = _run_paper_step(tmp_path, download_fails=True)

    assert result.returncode != 0
    assert (project / "_site/paper-previews/build-failed.txt").read_text().strip() == (
        "Could not download the paper discovery script."
    )


def test_workspace_can_pin_quarto_for_generated_sources() -> None:
    workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    assert workflow["on"]["workflow_call"]["inputs"]["quarto-version"]["default"] == (
        "release"
    )
    setup = next(
        step
        for step in workflow["jobs"]["build"]["steps"]
        if step.get("uses") == "quarto-dev/quarto-actions/setup@v2"
    )
    assert setup["with"]["version"] == "${{ inputs.quarto-version }}"


def test_workspace_assets_use_called_workflow_identity() -> None:
    workflow = WORKFLOW.read_text()

    assert workflow.count("${{ job.workflow_repository }}") == 4
    assert workflow.count("${{ job.workflow_sha }}") == 4
    assert "github.job_workflow" not in workflow


def test_workspace_deploy_commit_identifies_its_workflow_run() -> None:
    workflow = WORKFLOW.read_text()

    assert "git commit --allow-empty" in workflow
    assert (
        "Deploy ${{ github.event_name }} ${{ github.sha }} (run ${{ github.run_id }})"
        in workflow
    )
    assert "for asset in quarto-check.sh wait-for-preview.sh" in workflow


def test_workspace_checks_both_vendored_scripts_for_drift() -> None:
    workflow = WORKFLOW.read_text()

    assert "for asset in quarto-check.sh wait-for-preview.sh" in workflow


def test_scaffolded_workflow_follows_latest_release() -> None:
    """New projects follow the latest release, like the :latest image and CLI."""
    scaffold = (WORKSPACE_ASSETS / "docs.yml").read_text()
    match = re.search(r"workspace-quarto-site\.yml@(\S+)", scaffold)

    assert match is not None
    assert match.group(1) == "latest"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("latest", "latest"),
        ("v0.104.1", "v0.104.1"),
        ("main", "main"),
        ("feature/x", "feature/x"),
        ("a" * 40, "a" * 40),
        ("'latest'", "latest"),
        ('"v0.104.1"', "v0.104.1"),
        (None, "latest"),
    ],
)
def test_workspace_makefile_reads_workflow_ref(
    tmp_path: Path, value: str | None, expected: str
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    if value is not None:
        docs = project / ".github/workflows/docs.yml"
        docs.parent.mkdir(parents=True)
        quote = value[0] if value.startswith(("'", '"')) else ""
        ref = value.strip("'\"")
        docs.write_text(
            "  # uses: allenai/asta-plugins/.github/workflows/workspace-quarto-site.yml@ignored\n"
            f"  uses: {quote}allenai/asta-plugins/.github/workflows/workspace-quarto-site.yml@{ref}{quote}\n"
        )
    archive_root = tmp_path / "archive" / "asta-plugins-test"
    source = archive_root / WORKSPACE_ASSETS / "_extensions/evidence"
    source.mkdir(parents=True)
    (source / "snippet.lua").write_text("-- managed")
    archive = tmp_path / "asta-plugins.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(archive_root, arcname=archive_root.name)

    out = _run_workspace_assets(project, archive.as_uri())

    assert f"installed evidence extension from asta-plugins@{expected}" in out


def test_latest_release_ref_is_updated_before_images() -> None:
    workflow = yaml.load(
        Path(".github/workflows/docker.yml").read_text(), Loader=yaml.BaseLoader
    )
    ref_job = workflow["jobs"]["latest-ref"]
    image_job = workflow["jobs"]["latest"]

    assert ref_job["needs"] == "promote"
    assert ref_job["concurrency"]["group"] == "docker-release-latest-ref"
    assert ref_job["permissions"] == {"contents": "write"}
    assert image_job["needs"] == "latest-ref"
    assert image_job["permissions"] == {"contents": "read", "packages": "write"}


@pytest.mark.parametrize(
    ("current_release", "published_releases", "expected_release"),
    [
        ("v0.104.1", ("v0.104.1", "v0.105.0"), "v0.105.0"),
        ("v0.105.0", ("v0.104.1", "v0.105.0"), None),
        ("v0.105.0", ("v0.104.1",), None),
    ],
)
def test_latest_ref_selects_newest_release_after_lock(
    tmp_path: Path,
    current_release: str,
    published_releases: tuple[str, ...],
    expected_release: str | None,
) -> None:
    workflow = yaml.load(
        Path(".github/workflows/docker.yml").read_text(), Loader=yaml.BaseLoader
    )
    script = workflow["jobs"]["latest-ref"]["steps"][-1]["run"]
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True
    )
    source = repo / "source"
    source.write_text("first")
    subprocess.run(["git", "add", "source"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "first"], cwd=repo, check=True)
    subprocess.run(["git", "tag", "v0.104.1"], cwd=repo, check=True)
    old_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    source.write_text("second")
    subprocess.run(["git", "commit", "-qam", "second"], cwd=repo, check=True)
    subprocess.run(["git", "tag", "v0.105.0"], cwd=repo, check=True)
    new_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    subprocess.run(["git", "remote", "add", "origin", str(repo)], cwd=repo, check=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    published_tags = "|".join(
        f"ghcr.io/allenai/asta:{release}*" for release in published_releases
    )
    docker.write_text(
        "#!/bin/sh\n"
        'case "$4" in\n'
        f"  {published_tags}) exit 0 ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n"
    )
    docker.chmod(0o755)
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        'if [ "$2" = "-X" ]; then\n'
        '  for arg in "$@"; do\n'
        '    case "$arg" in\n'
        '      sha=*) printf "%s" "${arg#sha=}" > "$UPDATED_SHA" ;;\n'
        "      force=true) exit 1 ;;\n"
        "    esac\n"
        "  done\n"
        "else\n"
        '  printf "%s\\n" "$CURRENT_SHA"\n'
        "fi\n"
    )
    gh.chmod(0o755)
    updated_sha = tmp_path / "updated-sha"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GITHUB_REPOSITORY": "allenai/asta-plugins",
        "CURRENT_SHA": {"v0.104.1": old_sha, "v0.105.0": new_sha}[current_release],
        "UPDATED_SHA": str(updated_sha),
    }
    subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", script], cwd=repo, env=env, check=True
    )

    if expected_release is None:
        assert not updated_sha.exists()
    else:
        assert (
            updated_sha.read_text()
            == {
                "v0.104.1": old_sha,
                "v0.105.0": new_sha,
            }[expected_release]
        )


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("latest", "latest"),
        ("v0.104.1", "0.104.1"),
        ("'v0.104.1'", "0.104.1"),
        ("latest-foo", None),
        ("v0.104.1-rc.1", None),
        ("v0.104.1.2", None),
    ],
)
def test_manage_version_reads_complete_workspace_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ref: str, expected: str | None
) -> None:
    spec = importlib.util.spec_from_file_location(
        "manage_version", Path("scripts/manage-version.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    docs = tmp_path / "docs.yml"
    quote = ref[0] if ref.startswith(("'", '"')) else ""
    clean_ref = ref.strip("'\"")
    docs.write_text(
        "  uses: "
        f"{quote}allenai/asta-plugins/.github/workflows/workspace-quarto-site.yml@"
        f"{clean_ref}{quote}\n"
    )
    monkeypatch.setattr(module, "WORKSPACE_DOCS_WORKFLOW_FILE", docs)

    if expected is None:
        with pytest.raises(ValueError, match="Could not find workspace workflow ref"):
            module.get_workspace_workflow_version()
        monkeypatch.setattr(module, "INIT_FILE", tmp_path / "missing-init-file")
        assert module.set_version("0.105.0") is False
    else:
        assert module.get_workspace_workflow_version() == expected


@pytest.mark.parametrize(
    "uses_line",
    [
        "    uses: allenai/asta-plugins/.github/workflows/workspace-quarto-site.yml@v0.104.1",
        "    uses:   'allenai/asta-plugins/.github/workflows/workspace-quarto-site.yml@v0.104.1' # pinned",
        '    uses: "allenai/asta-plugins/.github/workflows/workspace-quarto-site.yml@v0.104.1"',
    ],
)
def test_manage_version_updates_any_accepted_pinned_workflow_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uses_line: str
) -> None:
    spec = importlib.util.spec_from_file_location(
        "manage_version", Path("scripts/manage-version.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for name in (
        "INIT_FILE",
        "PYPROJECT_FILE",
        "MARKETPLACE_FILE",
        "LOCK_FILE",
        "HOOK_FILE",
        "ASTA_CLI_SKILL_FILE",
    ):
        source = getattr(module, name)
        target = tmp_path / name / source.name
        target.parent.mkdir()
        target.write_bytes(source.read_bytes())
        monkeypatch.setattr(module, name, target)
    docs = tmp_path / "docs.yml"
    docs.write_text(f"jobs:\n  docs:\n{uses_line}\n")
    monkeypatch.setattr(module, "WORKSPACE_DOCS_WORKFLOW_FILE", docs)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "", ""),
    )

    assert module.get_workspace_workflow_version() == "0.104.1"
    assert module.set_version("0.105.0") is True
    assert (
        docs.read_text()
        == f"jobs:\n  docs:\n{uses_line.replace('v0.104.1', 'v0.105.0')}\n"
    )


def test_workspace_makefile_refreshes_evidence_extension(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive" / "asta-plugins-test"
    source = archive_root / WORKSPACE_ASSETS / "_extensions/evidence"
    shutil.copytree(WORKSPACE_ASSETS / "_extensions/evidence", source)

    archive = tmp_path / "asta-plugins.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(archive_root, arcname=archive_root.name)

    project = tmp_path / "project"
    target = project / "_extensions/evidence"
    target.mkdir(parents=True)
    (target / "stale-file").write_text("remove me")

    env = {
        "ASTA_PLUGINS_ARCHIVE_URL": archive.as_uri(),
        "PATH": os.environ["PATH"],
    }
    subprocess.run(
        [
            "make",
            "-f",
            str((WORKSPACE_ASSETS / "Makefile").resolve()),
            "workspace-assets",
        ],
        cwd=project,
        env=env,
        check=True,
    )

    assert not (target / "stale-file").exists()
    assert (target / "snippet.lua").read_bytes() == (
        WORKSPACE_ASSETS / "_extensions/evidence/snippet.lua"
    ).read_bytes()


def _run_workspace_assets(project: Path, archive_url: str) -> str:
    return subprocess.run(
        [
            "make",
            "-f",
            str((WORKSPACE_ASSETS / "Makefile").resolve()),
            "workspace-assets",
        ],
        cwd=project,
        env={"ASTA_PLUGINS_ARCHIVE_URL": archive_url, "PATH": os.environ["PATH"]},
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_workspace_makefile_leaves_symlinked_evidence_alone(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "snippet.lua").write_text("-- local edit")
    project = tmp_path / "project"
    (project / "_extensions").mkdir(parents=True)
    (project / "_extensions/evidence").symlink_to(checkout)

    out = _run_workspace_assets(project, (tmp_path / "unreachable.tar.gz").as_uri())

    assert "symlink" in out
    assert (project / "_extensions/evidence").is_symlink()
    assert (checkout / "snippet.lua").read_text() == "-- local edit"


def test_workspace_makefile_leaves_committed_evidence_alone(tmp_path: Path) -> None:
    project = tmp_path / "project"
    target = project / "_extensions/evidence"
    target.mkdir(parents=True)
    (target / "snippet.lua").write_text("-- customized")
    git = ["git", "-C", str(project), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "_extensions/evidence"], check=True)
    subprocess.run([*git, "commit", "-qm", "customize evidence"], check=True)

    out = _run_workspace_assets(project, (tmp_path / "unreachable.tar.gz").as_uri())

    assert "committed" in out
    assert (target / "snippet.lua").read_text() == "-- customized"


def test_workspace_makefile_does_not_race_an_active_install(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive" / "asta-plugins-test"
    source = archive_root / WORKSPACE_ASSETS / "_extensions/evidence"
    shutil.copytree(WORKSPACE_ASSETS / "_extensions/evidence", source)

    archive = tmp_path / "asta-plugins.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(archive_root, arcname=archive_root.name)

    project = tmp_path / "project"
    target = project / "_extensions/evidence"
    target.mkdir(parents=True)
    sentinel = target / "current-version"
    sentinel.write_text("keep me")
    (project / "_extensions/.evidence-install.lock").mkdir()

    env = {
        "ASTA_PLUGINS_ARCHIVE_URL": archive.as_uri(),
        "PATH": os.environ["PATH"],
    }
    result = subprocess.run(
        [
            "make",
            "-f",
            str((WORKSPACE_ASSETS / "Makefile").resolve()),
            "workspace-assets",
        ],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "another workspace-assets install is in progress" in result.stderr
    assert sentinel.read_text() == "keep me"


def test_workspace_makefile_keeps_cache_when_offline(tmp_path: Path) -> None:
    # A download failure (no network) with a previously fetched extension must
    # warn and keep the cached copy rather than fail — so a render works offline
    # (e.g. on a plane). Point the archive URL at a file that does not exist to
    # simulate an unreachable upstream.
    project = tmp_path / "project"
    cache = project / "_extensions/evidence"
    cache.mkdir(parents=True)
    sentinel = cache / "snippet.lua"
    sentinel.write_text("cached copy")

    env = {
        "ASTA_PLUGINS_ARCHIVE_URL": (tmp_path / "missing.tar.gz").as_uri(),
        "PATH": os.environ["PATH"],
    }
    result = subprocess.run(
        [
            "make",
            "-f",
            str((WORKSPACE_ASSETS / "Makefile").resolve()),
            "workspace-assets",
        ],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert "keeping the cached" in result.stderr
    assert sentinel.read_text() == "cached copy"


def test_workspace_makefile_fails_offline_without_cache(tmp_path: Path) -> None:
    # A download failure with no cached extension is a hard error: the first
    # fetch genuinely needs the network.
    project = tmp_path / "project"
    project.mkdir()

    env = {
        "ASTA_PLUGINS_ARCHIVE_URL": (tmp_path / "missing.tar.gz").as_uri(),
        "PATH": os.environ["PATH"],
    }
    result = subprocess.run(
        [
            "make",
            "-f",
            str((WORKSPACE_ASSETS / "Makefile").resolve()),
            "workspace-assets",
        ],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "no cached" in result.stderr
    assert not (project / "_extensions/evidence").exists()


def _write_fake_gh(bin_dir: Path) -> None:
    fake = bin_dir / "gh"
    fake.write_text(
        """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$GH_LOG"
case "$1 $2" in
  "repo view") echo owner/project ;;
  "run list")
    count=0
    [ ! -f "$GH_RUN_COUNT" ] || count=$(cat "$GH_RUN_COUNT")
    count=$((count + 1))
    printf '%s\\n' "$count" > "$GH_RUN_COUNT"
    [ "${GH_RUN_FAIL_ON:-0}" != "$count" ] || {
      echo '{"message":"temporary failure"}'
      exit 1
    }
    if [ "$count" -eq 1 ]; then
      echo "${GH_BEFORE_RUN:-100}"
    elif [ "$count" -ge "${GH_RUN_ON:-2}" ]; then
      echo "101"
    fi
    ;;
  "run view") echo "${GH_RUN_STATUS:-completed} ${GH_RUN_CONCLUSION:-success}" ;;
  "api repos/owner/project/branches/gh-pages")
    count=0
    [ ! -f "$GH_TIP_COUNT" ] || count=$(cat "$GH_TIP_COUNT")
    count=$((count + 1))
    printf '%s\\n' "$count" > "$GH_TIP_COUNT"
    if [ "$count" -eq 1 ] && [ "${GH_NO_BASELINE_BRANCH:-0}" = 1 ]; then
      echo 'gh: Not Found (HTTP 404)' >&2
      exit 1
    fi
    if [ "$count" -eq 1 ]; then echo before; else echo "${GH_AFTER_TIP:-before}"; fi
    ;;
  "api repos/owner/project/compare/before..."*)
    [ "${GH_COMPARE_FAIL:-0}" != 1 ] || {
      echo '{"message":"temporary failure"}'
      exit 1
    }
    jq_filter=
    while [ "$#" -gt 0 ]; do
      if [ "$1" = --jq ]; then jq_filter=$2; break; fi
      shift
    done
    marker_run=${GH_MARKER_RUN:-101}
    printf '{"status":"ahead","total_commits":1,"commits":[{"sha":"published-sha","commit":{"message":"Deploy pull_request abc (run %s)\\\\n"}}]}\\n' "$marker_run" | jq -r "$jq_filter"
    ;;
  "api repos/owner/project/commits?sha=gh-pages&per_page=100")
    jq_filter=
    while [ "$#" -gt 0 ]; do
      if [ "$1" = --jq ]; then jq_filter=$2; break; fi
      shift
    done
    marker_run=${GH_MARKER_RUN:-101}
    printf '[{"sha":"published-sha","commit":{"message":"Deploy pull_request abc (run %s)\\\\n"}}]\\n' "$marker_run" | jq -r "$jq_filter"
    ;;
  "api repos/owner/project/pages/builds?per_page=10")
    [ "${GH_PAGES_API_FAIL:-0}" != 1 ] || exit 1
    echo "${GH_BUILT:-1}"
    ;;
  *) echo "unexpected gh invocation: $*" >&2; exit 2 ;;
esac
"""
    )
    fake.chmod(0o755)


def _preview_project(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "seed",
            "--no-gpg-sign",
        ],
        cwd=project,
        check=True,
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_gh(bin_dir)
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GH_LOG": str(tmp_path / "gh.log"),
        "GH_RUN_COUNT": str(tmp_path / "run-count"),
        "GH_TIP_COUNT": str(tmp_path / "tip-count"),
        "WORKFLOW_TIMEOUT": "3",
        "RUN_TIMEOUT": "2",
        "PAGES_TIMEOUT": "2",
        "POLL": "1",
    }
    return project, env


def test_preview_wait_retries_lookup_from_detached_head(tmp_path: Path) -> None:
    project, env = _preview_project(tmp_path)
    script = (WORKSPACE_ASSETS / "wait-for-preview.sh").resolve()

    subprocess.run([script, "baseline"], cwd=project, env=env, check=True)
    subprocess.run(["git", "checkout", "--detach", "-q"], cwd=project, check=True)
    env.update(GH_RUN_ON="3", GH_RUN_FAIL_ON="2", GH_AFTER_TIP="after")
    result = subprocess.run(
        [script, "wait"], cwd=project, env=env, text=True, capture_output=True
    )

    assert result.returncode == 0, result.stderr
    assert "Pages published published-sha" in result.stdout
    run_lookups = [
        line
        for line in Path(env["GH_LOG"]).read_text().splitlines()
        if "run list" in line
    ]
    assert all("--branch" not in line for line in run_lookups)


def test_preview_wait_matches_pages_build_to_workflow_deployment(
    tmp_path: Path,
) -> None:
    project, env = _preview_project(tmp_path)
    script = (WORKSPACE_ASSETS / "wait-for-preview.sh").resolve()

    subprocess.run([script, "baseline"], cwd=project, env=env, check=True)
    env["GH_AFTER_TIP"] = "after"
    result = subprocess.run(
        [script, "wait"], cwd=project, env=env, text=True, capture_output=True
    )

    assert result.returncode == 0, result.stderr
    assert "Pages published published-sha" in result.stdout
    log = Path(env["GH_LOG"]).read_text()
    assert "compare/before...after" in log
    assert "(run 101)" in log
    assert "pages/builds?per_page=10" in log


def test_preview_wait_rejects_an_unidentified_pages_update(tmp_path: Path) -> None:
    project, env = _preview_project(tmp_path)
    script = (WORKSPACE_ASSETS / "wait-for-preview.sh").resolve()

    subprocess.run([script, "baseline"], cwd=project, env=env, check=True)
    env.update(GH_AFTER_TIP="after", GH_MARKER_RUN="999")
    result = subprocess.run(
        [script, "wait"], cwd=project, env=env, text=True, capture_output=True
    )

    assert result.returncode == 1
    assert "no identifiable run-ID marker" in result.stderr
    assert (project / ".git/preview-run-before").exists()


def test_preview_wait_supports_initial_pages_deployment(tmp_path: Path) -> None:
    project, env = _preview_project(tmp_path)
    script = (WORKSPACE_ASSETS / "wait-for-preview.sh").resolve()
    env.update(GH_NO_BASELINE_BRANCH="1", GH_AFTER_TIP="first-pages-tip")

    baseline = subprocess.run(
        [script, "baseline"], cwd=project, env=env, text=True, capture_output=True
    )
    result = subprocess.run(
        [script, "wait"], cwd=project, env=env, text=True, capture_output=True
    )

    assert baseline.returncode == 0, baseline.stderr
    assert result.returncode == 0, result.stderr
    assert "Pages published published-sha" in result.stdout
    assert "commits?sha=gh-pages&per_page=100" in Path(env["GH_LOG"]).read_text()


def test_preview_wait_preserves_baseline_when_correlation_fails(
    tmp_path: Path,
) -> None:
    project, env = _preview_project(tmp_path)
    script = (WORKSPACE_ASSETS / "wait-for-preview.sh").resolve()

    subprocess.run([script, "baseline"], cwd=project, env=env, check=True)
    env.update(GH_AFTER_TIP="after", GH_COMPARE_FAIL="1")
    result = subprocess.run(
        [script, "wait"], cwd=project, env=env, text=True, capture_output=True
    )

    assert result.returncode == 1
    assert "Could not correlate" in result.stderr
    assert (project / ".git/preview-run-before").exists()


def test_preview_wait_preserves_baseline_for_retry(tmp_path: Path) -> None:
    project, env = _preview_project(tmp_path)
    script = (WORKSPACE_ASSETS / "wait-for-preview.sh").resolve()

    subprocess.run([script, "baseline"], cwd=project, env=env, check=True)
    env.update(GH_RUN_ON="3", WORKFLOW_TIMEOUT="1", GH_AFTER_TIP="after")
    first = subprocess.run(
        [script, "wait"], cwd=project, env=env, text=True, capture_output=True
    )
    assert first.returncode == 1
    assert (project / ".git/preview-run-before").exists()

    second = subprocess.run(
        [script, "wait"], cwd=project, env=env, text=True, capture_output=True
    )
    assert second.returncode == 0, second.stderr
    assert not (project / ".git/preview-run-before").exists()


def test_preview_wait_bounds_workflow_completion(tmp_path: Path) -> None:
    project, env = _preview_project(tmp_path)
    script = (WORKSPACE_ASSETS / "wait-for-preview.sh").resolve()

    subprocess.run([script, "baseline"], cwd=project, env=env, check=True)
    env.update(GH_RUN_STATUS="queued", RUN_TIMEOUT="1")
    result = subprocess.run(
        [script, "wait"], cwd=project, env=env, text=True, capture_output=True
    )

    assert result.returncode == 1
    assert "did not complete within 1s" in result.stderr
    assert (project / ".git/preview-run-before").exists()


def test_preview_wait_reports_unreadable_pages_api(tmp_path: Path) -> None:
    project, env = _preview_project(tmp_path)
    script = (WORKSPACE_ASSETS / "wait-for-preview.sh").resolve()

    subprocess.run([script, "baseline"], cwd=project, env=env, check=True)
    env.update(GH_AFTER_TIP="after", GH_PAGES_API_FAIL="1", PAGES_TIMEOUT="1")
    result = subprocess.run(
        [script, "wait"], cwd=project, env=env, text=True, capture_output=True
    )

    assert result.returncode == 1
    assert "Could not read Pages builds" in result.stderr
    assert "verify Pages API access" in result.stderr
    assert (project / ".git/preview-run-before").exists()


def test_preview_wait_rejects_invalid_timing(tmp_path: Path) -> None:
    project, env = _preview_project(tmp_path)
    script = (WORKSPACE_ASSETS / "wait-for-preview.sh").resolve()
    env["POLL"] = "0"

    result = subprocess.run(
        [script, "baseline"], cwd=project, env=env, text=True, capture_output=True
    )

    assert result.returncode == 2
    assert "POLL must be a positive integer" in result.stderr


def test_preview_baseline_surfaces_run_lookup_failure(tmp_path: Path) -> None:
    project, env = _preview_project(tmp_path)
    script = (WORKSPACE_ASSETS / "wait-for-preview.sh").resolve()
    env["GH_RUN_FAIL_ON"] = "1"

    result = subprocess.run(
        [script, "baseline"], cwd=project, env=env, text=True, capture_output=True
    )

    assert result.returncode == 1
    assert "Could not read workflow runs" in result.stderr


def test_preview_wait_bounds_pages_poll_and_preserves_baseline(tmp_path: Path) -> None:
    project, env = _preview_project(tmp_path)
    script = (WORKSPACE_ASSETS / "wait-for-preview.sh").resolve()

    subprocess.run([script, "baseline"], cwd=project, env=env, check=True)
    env.update(GH_AFTER_TIP="after", GH_BUILT="0", PAGES_TIMEOUT="1")
    result = subprocess.run(
        [script, "wait"], cwd=project, env=env, text=True, capture_output=True
    )

    assert result.returncode == 1
    assert "Pages did not publish" in result.stderr
    assert (project / ".git/preview-run-before").exists()


def _make_evidence_archive(archive: Path) -> None:
    """Write a tarball whose layout mirrors an asta-plugins source archive."""
    archive_root = archive.parent / "asta-plugins-test"
    source = archive_root / WORKSPACE_ASSETS / "_extensions/evidence"
    if source.exists():
        shutil.rmtree(source)
    shutil.copytree(WORKSPACE_ASSETS / "_extensions/evidence", source)
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(archive_root, arcname=archive_root.name)


@pytest.mark.parametrize(
    ("ref", "archive_ref"),
    [
        (None, "refs/heads/latest"),
        ("v0.104.1", "refs/tags/v0.104.1"),
        ("v0.105.0-rc.1", "refs/tags/v0.105.0-rc.1"),
        ("feature/x", "refs/heads/feature/x"),
        ("a" * 40, "a" * 40),
    ],
)
def test_workspace_makefile_resolves_archive_ref(
    tmp_path: Path, ref: str | None, archive_ref: str
) -> None:
    repo = tmp_path / "asta-plugins"
    (repo / "archive").mkdir(parents=True)
    archive = repo / f"archive/{archive_ref}.tar.gz"
    archive.parent.mkdir(parents=True, exist_ok=True)
    _make_evidence_archive(archive)

    project = tmp_path / "project"
    project.mkdir()
    if ref is not None:
        docs = project / ".github/workflows/docs.yml"
        docs.parent.mkdir(parents=True)
        docs.write_text(
            "  uses: allenai/asta-plugins/.github/workflows/"
            f"workspace-quarto-site.yml@{ref}\n"
        )
    env = {
        "ASTA_PLUGINS_REPO": repo.as_uri(),
        "PATH": os.environ["PATH"],
    }
    result = subprocess.run(
        [
            "make",
            "-f",
            str((WORKSPACE_ASSETS / "Makefile").resolve()),
            "workspace-assets",
        ],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert f"asta-plugins@{ref or 'latest'}" in result.stdout
    assert (project / "_extensions/evidence/snippet.lua").read_bytes() == (
        WORKSPACE_ASSETS / "_extensions/evidence/snippet.lua"
    ).read_bytes()
