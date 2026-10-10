# A committed scripts/<name> wins; otherwise use the copy `asta workspace sync` caches.
ASTA_WORKSPACE_MANAGED_SCRIPTS := 1
ASTA_WORKSPACE_SCRIPTS ?= .asta/cache/scripts
PYTHON ?= python3
ASTA_WORKSPACE_VIEWERS ?= 1
workspace_script = $(or $(firstword $(wildcard scripts/$(1) $(ASTA_WORKSPACE_SCRIPTS)/$(1))),$(error Missing $(1): update the Asta CLI and run 'asta workspace sync --refresh' or add scripts/$(1) to customize it))

.PHONY: preview render clean dev deployed-url check workspace-shared-check workspace-assets preview-baseline preview-ready workspace-viewers

# The project Makefile passes its selected workflow ref to the evidence fetch.
# Standalone use can set ASTA_PLUGINS_REF or resolve the latest release tag.
ASTA_PLUGINS_REPO ?= https://github.com/allenai/asta-plugins
ASTA_PLUGINS_REF ?=
# Derived from the repo + resolved ref unless set explicitly (tests point it at
# a local archive). When set, it is used verbatim and ref resolution is skipped.
ASTA_PLUGINS_ARCHIVE_URL ?=

# The evidence extension is maintained with the workspace skill rather than
# vendored into every report. Replace it only after a complete download and
# extraction so a network failure cannot leave a partial extension behind.
#
# Offline-tolerant: if the network can't be reached (tag resolution or download
# fails) but a previously fetched _extensions/evidence already exists, keep that
# cached copy and warn instead of failing — so a render works on a plane. Only a
# first fetch with no cache is a hard error.
workspace-assets:
	@set -eu; \
	if [ -L _extensions/evidence ]; then \
		echo "workspace-assets: _extensions/evidence is a symlink (local development); not refreshing"; exit 0; \
	fi; \
	if git ls-files --error-unmatch _extensions/evidence >/dev/null 2>&1; then \
		echo "workspace-assets: _extensions/evidence is committed (customized copy); not refreshing"; exit 0; \
	fi; \
	ref='$(subst ','"'"',$(value ASTA_PLUGINS_REF))'; \
	archive='$(subst ','"'"',$(value ASTA_WORKSPACE_ARCHIVE))'; \
	url='$(subst ','"'"',$(value ASTA_PLUGINS_ARCHIVE_URL))'; \
	repo='$(subst ','"'"',$(value ASTA_PLUGINS_REPO))'; \
	have_cache=0; \
	if [ -d _extensions/evidence ] || [ -L _extensions/evidence ]; then have_cache=1; fi; \
	offline_ok() { \
		if [ "$$have_cache" -eq 1 ]; then \
			echo "workspace-assets: could not reach asta-plugins ($$1); keeping the cached _extensions/evidence — re-run with network access to refresh" >&2; \
			exit 0; \
		fi; \
		echo "workspace-assets: could not reach asta-plugins ($$1) and no cached _extensions/evidence exists — network access is required for the first fetch" >&2; \
		exit 1; \
	}; \
	if [ -z "$$url" ]; then \
		if [ -z "$$ref" ]; then \
			ref=$$(git ls-remote --tags --refs "$$repo" 'v*' 2>/dev/null \
				| awk -F/ '{print $$NF}' \
				| grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$$' \
				| sort -V | tail -n 1) || true; \
			[ -n "$$ref" ] || offline_ok "could not resolve the latest version tag from $$repo"; \
		fi; \
		if printf '%s\n' "$$ref" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$$'; then \
			url="$$repo/archive/refs/tags/$$ref.tar.gz"; \
		elif [ "$$ref" = latest ] || [ "$$ref" = main ]; then \
			url="$$repo/archive/refs/heads/$$ref.tar.gz"; \
		else \
			url="$$repo/archive/$$ref.tar.gz"; \
		fi; \
	fi; \
	tmp=$$(mktemp -d); \
	lock=_extensions/.evidence-install.lock; \
	backup="$$tmp/previous-evidence"; \
	lock_held=0; \
	cleanup() { \
		status=$$?; \
		trap - 0 1 2 15; \
		if [ "$$status" -ne 0 ] && { [ -e "$$backup" ] || [ -L "$$backup" ]; }; then \
			rm -rf _extensions/evidence; \
			mv "$$backup" _extensions/evidence || status=1; \
		fi; \
		[ "$$lock_held" -eq 0 ] || rmdir "$$lock" 2>/dev/null || true; \
		rm -rf "$$tmp"; \
		exit "$$status"; \
	}; \
	trap cleanup 0; \
	trap 'exit 1' 1 2 15; \
	if [ -n "$$archive" ]; then \
		[ -s "$$archive" ] || offline_ok "managed source archive is missing"; \
		cp "$$archive" "$$tmp/asta-plugins.tar.gz"; \
	else \
		curl -fsSL "$$url" -o "$$tmp/asta-plugins.tar.gz" || offline_ok "download from $$url failed"; \
	fi; \
	tar -xzf "$$tmp/asta-plugins.tar.gz" -C "$$tmp"; \
	source_dir=$$(find "$$tmp" -type d -path '*/plugins/asta-tools/skills/workspace/assets/_extensions/evidence' -print -quit); \
	[ -n "$$source_dir" ] || { echo "evidence extension not found in asta-plugins@$${ref:-$$url}" >&2; exit 1; }; \
	cp -R "$$source_dir" "$$tmp/evidence"; \
	mkdir -p _extensions; \
	mkdir "$$lock" 2>/dev/null || { echo "another workspace-assets install is in progress" >&2; exit 1; }; \
	lock_held=1; \
	if [ -e _extensions/evidence ] || [ -L _extensions/evidence ]; then \
		mv _extensions/evidence "$$backup"; \
	fi; \
	mv "$$tmp/evidence" _extensions/evidence; \
	echo "workspace-assets: installed evidence extension from asta-plugins@$${ref:-$$url}"

workspace-viewers:
	@set -eu; \
	[ '$(subst ','"'"',$(ASTA_WORKSPACE_VIEWERS))' != 0 ] || exit 0; \
	discovery='$(subst ','"'"',$(firstword $(wildcard scripts/paper-discovery.py $(ASTA_WORKSPACE_SCRIPTS)/paper-discovery.py)))'; \
	viewer='$(subst ','"'"',$(firstword $(wildcard scripts/paper-viewer.py $(ASTA_WORKSPACE_SCRIPTS)/paper-viewer.py)))'; \
	if [ -z "$$discovery" ] || [ -z "$$viewer" ]; then \
		if find . -type d \( -name node_modules -o -name _site -o -name .asta -o -name .git -o -name venv -o -name .venv -o -name paper-previews \) -prune -o -type f -name main.tex -print -quit | grep -q .; then \
			[ -n "$$discovery" ] || echo "workspace-viewers: missing paper-discovery.py" >&2; \
			[ -n "$$viewer" ] || echo "workspace-viewers: missing paper-viewer.py" >&2; \
			echo "workspace-viewers: update the Asta CLI and run 'asta workspace sync --refresh --require-scripts' before removing existing viewer pages" >&2; \
		fi; exit 0; \
	fi; \
	python='$(subst ','"'"',$(PYTHON))'; \
	if ! command -v "$$python" >/dev/null 2>&1; then \
		echo "workspace-viewers: $$python is unavailable; keeping existing viewer pages" >&2; exit 0; \
	fi; \
	tmp=$$(mktemp); trap 'rm -f "$$tmp"' 0; \
	"$$python" "$$discovery" > "$$tmp"; \
	"$$python" "$$viewer" < "$$tmp"

preview: workspace-assets workspace-viewers
	quarto preview --no-browser

render: workspace-assets workspace-viewers
	quarto render

# Run the same quality gates CI runs, in one place so local and CI can't
# drift. CI's docs workflow calls this target — when a project grows a new
# gate, add it here (or as a prerequisite target), never as an inline workflow
# step. The render/validate script comes from the workspace cache unless the
# project supplies scripts/quarto-check.sh.
# Projects can require this marker so a custom rules file cannot make their
# `check` target pass without the shared quality gate.
ASTA_WORKSPACE_CHECK := 1
check: workspace-shared-check
workspace-shared-check: workspace-assets workspace-viewers
	sh $(call workspace_script,quarto-check.sh)

clean:
	rm -rf _site .quarto

# Open VS Code attached to the devcontainer.
dev:
	@code --folder-uri "vscode-remote://dev-container+$$(printf '%s' "$$(pwd)" | xxd -p | tr -d '\n')/workspaces/$$(basename "$$(pwd)")"

# Print the deployed URL the user can visit.
# On main: the GitHub Pages root. On a feature branch: the PR's preview URL.
deployed-url:
	@branch=$$(git rev-parse --abbrev-ref HEAD); \
	if [ "$$branch" = "main" ]; then \
		gh repo view --json owner,name -q '"https://" + .owner.login + ".github.io/" + .name + "/"'; \
	else \
		pr=$$(gh pr view --json url -q .url 2>/dev/null) || { echo "No PR for $$branch yet — push the branch and open a PR first." >&2; exit 1; }; \
		echo "PR: $$pr"; \
		preview=$$(gh pr view --json comments -q '.comments[] | select(.body | test("Preview:")) | .body' 2>/dev/null | tail -1); \
		[ -n "$$preview" ] && echo "$$preview" || echo "(Preview URL not posted yet — CI may still be running.)"; \
	fi

# Preview readiness, for automated callers that report a preview link: mark the
# Pages tip and latest docs run before pushing, then block until this push's
# deployment is live.
preview-baseline:
	sh $(call workspace_script,wait-for-preview.sh) baseline

preview-ready:
	sh $(call workspace_script,wait-for-preview.sh) wait

# The paper's latexmkrc selects its engine and bibliography search path.
PAPER_DIR ?= paper
.PHONY: paper paper-clean
# Main document: main.tex, else the single .tex file containing \documentclass.
PAPER_MAIN = cd "$(PAPER_DIR)" 2>/dev/null || { echo "No paper directory $(PAPER_DIR)" >&2; exit 1; }; \
	if [ -f main.tex ] && [ ! -L main.tex ]; then main=main.tex; else \
	main=; count=0; for file in *.tex; do \
	if [ -f "$$file" ] && [ ! -L "$$file" ] && grep -Eq '^[^%]*\\documentclass[[:blank:]]*(\{|\[)' -- "$$file"; then main=$$file; count=$$((count+1)); fi; done; \
	[ $$count -eq 1 ] || { echo "$(PAPER_DIR): add main.tex, or keep exactly one .tex file with documentclass" >&2; exit 1; }; fi
paper:
	@$(PAPER_MAIN); printf 'latexmk -synctex=1 -interaction=nonstopmode -halt-on-error -file-line-error -outdir=build "%s"\n' "$$main"; latexmk -synctex=1 -interaction=nonstopmode -halt-on-error -file-line-error -outdir=build "$$main"

paper-clean:
	@$(PAPER_MAIN); printf 'latexmk -C -outdir=build "%s"\n' "$$main"; latexmk -C -outdir=build "$$main"
