import json
from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/workspace-quarto-site.yml")
ASSETS = Path("plugins/asta-tools/skills/workspace/assets")
RULESETS = ASSETS / "rulesets"


def _load(name: str) -> dict:
    return json.loads((RULESETS / name).read_text())


def _check_context(job: str) -> str:
    """The context GitHub reports for a reusable-workflow job: `<caller job> / <job name>`."""
    stub = yaml.load((ASSETS / "docs.yml").read_text(), Loader=yaml.BaseLoader)
    (caller,) = stub["jobs"]
    jobs = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)["jobs"]
    return f"{caller} / {jobs[job].get('name', job)}"


def test_rulesets_target_the_default_branch():
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
