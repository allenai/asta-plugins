import os
import re
import shutil
import subprocess
import tarfile
import tomllib
from pathlib import Path

WORKFLOW = Path(".github/workflows/workspace-quarto-site.yml")
WORKSPACE_ASSETS = Path("plugins/asta-tools/skills/workspace/assets")


def test_workspace_assets_use_called_workflow_identity() -> None:
    workflow = WORKFLOW.read_text()

    assert workflow.count("${{ job.workflow_repository }}") == 2
    assert workflow.count("${{ job.workflow_sha }}") == 2
    assert "github.job_workflow" not in workflow


def test_workspace_deploy_commit_identifies_its_workflow_run() -> None:
    workflow = WORKFLOW.read_text()

    assert "git commit --allow-empty" in workflow
    assert (
        "Deploy ${{ github.event_name }} ${{ github.sha }} (run ${{ github.run_id }})"
        in workflow
    )
    assert "for asset in quarto-check.sh wait-for-preview.sh check-evidence.py" in workflow


def test_workspace_checks_vendored_scripts_for_drift() -> None:
    workflow = WORKFLOW.read_text()

    assert "for asset in quarto-check.sh wait-for-preview.sh check-evidence.py" in workflow


def test_scaffolded_workflow_ref_matches_project_version() -> None:
    """Release-managed workspace assets must advance under one version tag."""
    project_version = tomllib.loads(Path("pyproject.toml").read_text())["project"][
        "version"
    ]
    scaffold = (WORKSPACE_ASSETS / "docs.yml").read_text()
    match = re.search(r"workspace-quarto-site\.yml@v([0-9.]+)", scaffold)

    assert match is not None
    assert match.group(1) == project_version


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


def test_workspace_makefile_resolves_latest_version_tag(tmp_path: Path) -> None:
    # A local git repo standing in for asta-plugins: git ls-remote reads its
    # tags, and curl reads a co-located archive/ dir via file://. The default
    # (no ASTA_PLUGINS_REF, no ASTA_PLUGINS_ARCHIVE_URL) must pick the highest
    # semver tag and skip non-version tags.
    repo = tmp_path / "asta-plugins"
    (repo / "archive").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
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
        check=True,
    )
    for tag in ("v0.2.0", "v0.10.0", "v0.9.0", "v2-reproduction-work"):
        subprocess.run(["git", "-C", str(repo), "tag", tag], check=True)

    # Only the latest semver tag's archive exists; if resolution picked any
    # other ref (main, v2-reproduction-work, v0.9.0), the curl would 404.
    _make_evidence_archive(repo / "archive/v0.10.0.tar.gz")

    project = tmp_path / "project"
    project.mkdir()
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
    assert "asta-plugins@v0.10.0" in result.stdout
    assert (project / "_extensions/evidence/snippet.lua").read_bytes() == (
        WORKSPACE_ASSETS / "_extensions/evidence/snippet.lua"
    ).read_bytes()
