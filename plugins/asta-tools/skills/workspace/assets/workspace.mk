# A committed scripts/<name> wins; otherwise use the copy `asta workspace sync` caches.
ASTA_WORKSPACE_MANAGED_SCRIPTS := 1
# Oldest asta CLI these rules work with; `asta workspace sync` checks it.
ASTA_WORKSPACE_MIN_CLI := 0.106.0
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

# Managed Quarto extensions: the evidence filter and the Asta site theme. They
# are maintained with the workspace skill rather than vendored into every report.
# Replace them only after a complete download and extraction so a network failure
# cannot leave a partial extension behind.
#
# Offline-tolerant: if the network can't be reached (tag resolution or download
# fails) but all extensions referenced by _quarto.yml are cached, keep those
# copies and warn instead of failing. Missing required cached assets are a hard
# error. The theme ships its own fonts, so cached copies render offline.
workspace-assets:
	@set -eu; \
	required_exts=evidence; \
	if cat _quarto*.yml 2>/dev/null | sed '/^[[:space:]]*#/d' | grep -Eq '_extensions/asta-theme/(light\.scss|dark\.scss|asta\.css|asta-head\.html)'; then \
		required_exts="$$required_exts asta-theme"; \
	fi; \
	exts=; \
	for ext in $$required_exts; do \
		if [ -L "_extensions/$$ext" ]; then \
			echo "workspace-assets: _extensions/$$ext is a symlink (local development); not refreshing"; \
		elif git ls-files --error-unmatch "_extensions/$$ext" >/dev/null 2>&1; then \
			echo "workspace-assets: _extensions/$$ext is committed (customized copy); not refreshing"; \
		else exts="$$exts $$ext"; fi; \
	done; \
	[ -n "$$exts" ] || exit 0; \
	ref='$(subst ','"'"',$(value ASTA_PLUGINS_REF))'; \
	archive='$(subst ','"'"',$(value ASTA_WORKSPACE_ARCHIVE))'; \
	url='$(subst ','"'"',$(value ASTA_PLUGINS_ARCHIVE_URL))'; \
	repo='$(subst ','"'"',$(value ASTA_PLUGINS_REPO))'; \
	have_cache=1; \
	for ext in $$required_exts; do \
		[ -d "_extensions/$$ext" ] || have_cache=0; \
	done; \
	case " $$required_exts " in *' asta-theme '*) \
		for file in light.scss dark.scss asta.css asta-head.html fonts/Manrope.woff2 fonts/RobotoMono.woff2; do \
			[ -s "_extensions/asta-theme/$$file" ] || have_cache=0; \
		done ;; esac; \
	offline_ok() { \
		if [ "$$have_cache" -eq 1 ]; then \
			echo "workspace-assets: could not reach asta-plugins ($$1); keeping the cached extensions — re-run with network access to refresh" >&2; \
			exit 0; \
		fi; \
		echo "workspace-assets: could not reach asta-plugins ($$1) and no cached copy of all required extensions exists — network access is required for the first fetch" >&2; \
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
	backup="$$tmp/previous"; \
	lock_held=0; \
	installing=; \
	cleanup() { \
		status=$$?; \
		trap - 0 1 2 15; \
		if [ "$$status" -ne 0 ]; then \
			for ext in $$installing; do rm -rf "_extensions/$$ext"; done; \
			for ext in $$exts; do \
				if [ -e "$$backup/$$ext" ] || [ -L "$$backup/$$ext" ]; then \
					rm -rf "_extensions/$$ext"; \
					mv "$$backup/$$ext" "_extensions/$$ext" || status=1; \
				fi; \
			done; \
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
	mkdir "$$tmp/new" "$$backup"; \
	for ext in $$exts; do \
		source_dir=$$(find "$$tmp" -type d -path "*/plugins/asta-tools/skills/workspace/assets/_extensions/$$ext" -print -quit); \
		if [ -z "$$source_dir" ]; then \
			case " $$required_exts " in *" $$ext "*) \
				echo "$$ext extension not found in asta-plugins@$${ref:-$$url}; select a ref that supplies it before rendering this _quarto.yml" >&2; exit 1 ;; esac; \
			echo "workspace-assets: asta-plugins@$${ref:-$$url} has no $$ext extension; skipping" >&2; continue; \
		fi; \
		cp -R "$$source_dir" "$$tmp/new/$$ext"; \
	done; \
	mkdir -p _extensions; \
	mkdir "$$lock" 2>/dev/null || { echo "another workspace-assets install is in progress" >&2; exit 1; }; \
	lock_held=1; \
	for ext in $$exts; do \
		[ -d "$$tmp/new/$$ext" ] || continue; \
		if [ -e "_extensions/$$ext" ] || [ -L "_extensions/$$ext" ]; then \
			mv "_extensions/$$ext" "$$backup/$$ext"; \
		fi; \
		installing="$$installing $$ext"; \
		mv "$$tmp/new/$$ext" "_extensions/$$ext"; \
		echo "workspace-assets: installed $$ext extension from asta-plugins@$${ref:-$$url}"; \
	done

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
	main=; count=0; for file in *.tex .*.tex; do \
	if [ -f "$$file" ] && [ ! -L "$$file" ] && python3 -c 'import pathlib,re,sys; sys.exit(not re.search(r"(?m)^[^\n]*(?<!\\)(?:\\\\)*\\documentclass\s*[\[{]", re.sub(r"(?<!\\)((?:\\\\)*)%[^\n]*", r"\1", pathlib.Path(sys.argv[1]).read_text(errors="replace"))))' "$$file"; then main=$$file; count=$$((count+1)); fi; done; \
	[ $$count -eq 1 ] || { echo "$(PAPER_DIR): add main.tex, or keep exactly one .tex file with documentclass" >&2; exit 1; }; fi
paper:
	@$(PAPER_MAIN); printf 'latexmk -synctex=1 -interaction=nonstopmode -halt-on-error -file-line-error -outdir=build "%s"\n' "./$$main"; latexmk -synctex=1 -interaction=nonstopmode -halt-on-error -file-line-error -outdir=build "./$$main"

paper-clean:
	@$(PAPER_MAIN); printf 'latexmk -C -outdir=build "%s"\n' "./$$main"; latexmk -C -outdir=build "./$$main"
