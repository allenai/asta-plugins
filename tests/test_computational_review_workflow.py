"""The Computational review workflow reads ComputationalReviewTemplate upstream, at one commit.

Nothing of the template is copied into the plugin; the workflow links its README and skills
directory at a pinned commit, and run-workflow's index links the workflow.
"""

import re
from pathlib import Path

RUN_WORKFLOW = (
    Path(__file__).resolve().parent.parent / "plugins/asta-flows/skills/run-workflow"
)
WORKFLOW = RUN_WORKFLOW / "workflows/review/README.md"
REPO = "https://github.com/AllenNeuralDynamics/ComputationalReviewTemplate"


def test_the_template_is_linked_not_vendored():
    folder = RUN_WORKFLOW / "workflows/review"
    assert [p.name for p in folder.iterdir()] == ["README.md"]
    text = WORKFLOW.read_text()
    pins = set(re.findall(r"\b[0-9a-f]{40}\b", text))
    assert len(pins) == 1, pins
    (ref,) = pins
    assert f"{REPO}/tree/{ref}#readme" in text
    assert f"{REPO}/tree/{ref}/skills" in text
    assert f"REF={ref}" in text


def test_index_links_the_workflow():
    skill = (RUN_WORKFLOW / "SKILL.md").read_text()
    assert "](workflows/review/README.md)" in skill
