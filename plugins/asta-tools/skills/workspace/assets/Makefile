.PHONY: preview render clean dev deployed-url check workspace-assets preview-baseline preview-ready

# Which asta-plugins ref to fetch the workspace evidence extension from.
# The default (empty ASTA_PLUGINS_REF) resolves to the latest published version
# tag, so projects pick up new releases automatically — the same way other
# asta-plugins consumers upgrade, rather than tracking the mutable main branch.
# Pin a specific release with ASTA_PLUGINS_REF=v0.103.0, or track the in-flight
# branch with ASTA_PLUGINS_REF=main.
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
# error. Web fonts still need network access; offline pages use fallback fonts.
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
	url='$(subst ','"'"',$(value ASTA_PLUGINS_ARCHIVE_URL))'; \
	repo='$(subst ','"'"',$(value ASTA_PLUGINS_REPO))'; \
	have_cache=1; \
	for ext in $$required_exts; do \
		[ -d "_extensions/$$ext" ] || have_cache=0; \
	done; \
	case " $$required_exts " in *' asta-theme '*) \
		for file in light.scss dark.scss asta.css asta-head.html; do \
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
		url="$$repo/archive/$$ref.tar.gz"; \
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
	curl -fsSL "$$url" -o "$$tmp/asta-plugins.tar.gz" || offline_ok "download from $$url failed"; \
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

preview: workspace-assets
	quarto preview --no-browser

render: workspace-assets
	quarto render

# Run the same quality gates CI runs, in one place so local and CI can't
# drift. CI's docs workflow calls this target — when a project grows a new
# gate, add it here (or as a prerequisite target), never as an inline workflow
# step. The shared render/validate logic is vendored in scripts/quarto-check.sh
# (from the workspace skill; update by re-copying, don't hand-edit).
check: workspace-assets
	sh scripts/quarto-check.sh

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
# deployment is live. Vendored from the workspace skill — update by re-copying.
preview-baseline:
	sh scripts/wait-for-preview.sh baseline

preview-ready:
	sh scripts/wait-for-preview.sh wait
