.PHONY: preview render clean dev deployed-url check workspace-assets

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
	ref="$(ASTA_PLUGINS_REF)"; \
	url="$(ASTA_PLUGINS_ARCHIVE_URL)"; \
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
			ref=$$(git ls-remote --tags --refs "$(ASTA_PLUGINS_REPO)" 'v*' 2>/dev/null \
				| awk -F/ '{print $$NF}' \
				| grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$$' \
				| sort -V | tail -n 1) || true; \
			[ -n "$$ref" ] || offline_ok "could not resolve the latest version tag from $(ASTA_PLUGINS_REPO)"; \
		fi; \
		url="$(ASTA_PLUGINS_REPO)/archive/$$ref.tar.gz"; \
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
	curl -fsSL "$$url" -o "$$tmp/asta-plugins.tar.gz" || offline_ok "download from $$url failed"; \
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
