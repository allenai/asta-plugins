import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/workspace-quarto-site.yml"
ASSETS = ROOT / "plugins/asta-tools/skills/workspace/assets"
RULESETS = ASSETS / "rulesets"


def _load(name: str) -> dict:
    return json.loads((RULESETS / name).read_text())


def _check_context(job: str) -> str:
    """The context GitHub reports for a reusable-workflow job: `<caller job> / <job name>`."""
    stub = yaml.load((ASSETS / "docs.yml").read_text(), Loader=yaml.BaseLoader)
    callers = [
        (job_id, config)
        for job_id, config in stub["jobs"].items()
        if config.get("uses", "").startswith(
            "allenai/asta-plugins/.github/workflows/workspace-quarto-site.yml@"
        )
    ]
    assert len(callers) == 1, "Expected one caller of workspace-quarto-site.yml"
    caller_id, caller_job = callers[0]
    caller = caller_job.get("name", caller_id)
    jobs = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)["jobs"]
    for job_id, config in ((caller_id, caller_job), (job, jobs[job])):
        assert "strategy" not in config, (
            f"{job_id}: matrix check names need ruleset updates"
        )
        assert "${{" not in config.get("name", job_id), (
            f"{job_id}: dynamic check names need ruleset updates"
        )
    return f"{caller} / {jobs[job].get('name', job)}"


def test_rulesets_target_the_default_branch():
    assert {path.name for path in RULESETS.glob("*.json")} == {
        "default-branch.json",
        "docs-checks.json",
    }
    for path in RULESETS.glob("*.json"):
        ruleset = json.loads(path.read_text())
        assert ruleset["target"] == "branch", path
        assert ruleset["enforcement"] == "active", path
        assert ruleset["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"], path


def test_default_branch_ruleset_blocks_force_push_and_deletion():
    rules = {rule["type"] for rule in _load("default-branch.json")["rules"]}
    assert rules == {"deletion", "non_fast_forward"}


def test_docs_checks_match_reusable_workflow_jobs():
    (rule,) = _load("docs-checks.json")["rules"]
    assert rule["type"] == "required_status_checks"
    contexts = [c["context"] for c in rule["parameters"]["required_status_checks"]]
    assert contexts == [_check_context("build"), _check_context("paper-gate")]


def test_docs_checks_require_github_actions_source():
    (rule,) = _load("docs-checks.json")["rules"]
    checks = rule["parameters"]["required_status_checks"]
    assert all(check.get("integration_id") == 15368 for check in checks)


def test_pages_asset_serves_gh_pages_root():
    pages = json.loads((ASSETS / "github-pages.json").read_text())
    assert pages == {
        "build_type": "legacy",
        "source": {"branch": "gh-pages", "path": "/"},
    }
