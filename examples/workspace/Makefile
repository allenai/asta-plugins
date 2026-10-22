# This release-owned example loads shared rules from the same checkout.
.DEFAULT_GOAL := preview
include workspace.mk

# Project-owned demo targets stay here; shared rules also provide paper builds.
.PHONY: check demo-source-tests demo-build demo-check preview-artifact-check workspace-check-gate

check: workspace-check-gate demo-source-tests
workspace-check-gate:
	@test "$(ASTA_WORKSPACE_CHECK)" = 1 || { echo "shared workspace check rules are missing" >&2; exit 1; }

demo-source-tests:
	python3 -m unittest discover -s tests -v

demo-build:
	python3 scripts/build-demo.py "$${SITE_DIR:-_site}"

demo-check:
	python3 scripts/refresh-demo.py check "$${DEMO_DIR:?set DEMO_DIR to a built demo snapshot}"

preview-artifact-check: demo-build
	python3 scripts/refresh-demo.py check "$${SITE_DIR:-_site}/demo"
	bash ../../plugins/asta-tools/skills/workspace/assets/paper-preview.sh "" paper
	sh scripts/check-paper.sh "$${SITE_DIR:-_site}"
