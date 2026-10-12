# Compact entry point; managed scripts require Asta CLI 0.106.0 or newer.
# A local workspace.mk takes precedence when a project customizes shared rules.
# Shared scripts are cached; a committed project copy overrides them.
.DEFAULT_GOAL := preview
# Artifact checks use the cache prepared by make check, without another CLI sync.
ASTA_PROJECT_ONLY := demo-source-tests demo-build demo-check preview-artifact-check paper paper-clean
ifneq ($(strip $(MAKECMDGOALS)),)
ifeq ($(strip $(filter-out $(ASTA_PROJECT_ONLY),$(MAKECMDGOALS))),)
ASTA_SKIP_SHARED := 1
endif
endif

ifeq ($(ASTA_SKIP_SHARED),)
ifneq ($(wildcard workspace.mk),)
include workspace.mk
else
ifneq ($(origin ASTA_PLUGINS_REF),undefined)
$(error ASTA_PLUGINS_REF cannot select managed rules; change the ref in .github/workflows/docs.yml)
endif
include .asta/cache/workspace.mk
.asta/cache/workspace.mk: .github/workflows/docs.yml
	@command -v asta >/dev/null || { echo 'Install the Asta CLI to load workspace rules, or add a local workspace.mk' >&2; exit 1; }
	@asta workspace sync
	@touch $@
endif
endif

.PHONY: update-workspace
update-workspace:
	asta workspace sync --refresh

# Project-owned demo and hand-written paper targets stay here.
.PHONY: check demo-source-tests demo-build demo-check preview-artifact-check print-asta-plugins-ref paper paper-clean workspace-check-gate

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
	python3 scripts/refresh-demo.py check "$${SITE_DIR:-_site}/demo/showcase"
	bash ../../plugins/asta-tools/skills/workspace/assets/paper-preview.sh "" paper
	sh scripts/check-paper.sh "$${SITE_DIR:-_site}"

print-asta-plugins-ref:
	@printf '%s\n' "$(ASTA_PLUGINS_REF)"

paper:
	cd paper && latexmk -pdf -synctex=1 -interaction=nonstopmode -halt-on-error -file-line-error -outdir=build main.tex

paper-clean:
	cd paper && latexmk -C -outdir=build main.tex
