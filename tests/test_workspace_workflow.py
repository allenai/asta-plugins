from pathlib import Path

WORKFLOW = Path(".github/workflows/workspace-quarto-site.yml")


def test_workspace_assets_use_called_workflow_identity() -> None:
    workflow = WORKFLOW.read_text()

    assert workflow.count("${{ job.workflow_repository }}") == 2
    assert workflow.count("${{ job.workflow_sha }}") == 2
    assert "github.job_workflow" not in workflow
