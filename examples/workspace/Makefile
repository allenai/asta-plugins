# This release-owned example loads shared rules from the same checkout.
.DEFAULT_GOAL := preview
include workspace.mk

# Project-owned checks stay here; shared rules also provide paper builds.
.PHONY: check preview-artifact-check workspace-check-gate

check: workspace-check-gate
workspace-check-gate:
	@test "$(ASTA_WORKSPACE_CHECK)" = 1 || { echo "shared workspace check rules are missing" >&2; exit 1; }

preview-artifact-check:
	ASTA_PAPER_STRICT=1 bash ../../plugins/asta-tools/skills/workspace/assets/paper-preview.sh "" paper
	sh scripts/check-paper.sh "$${SITE_DIR:-_site}"
