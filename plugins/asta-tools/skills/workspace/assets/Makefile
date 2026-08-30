.PHONY: preview render clean dev deployed-url check workspace-assets

# Follow the workspace assets on asta-plugins main by default, matching the
# reusable docs workflow below. Set ASTA_PLUGINS_REF to pin both when a project
# prefers explicit upgrades.
ASTA_PLUGINS_REF ?= main
ASTA_PLUGINS_ARCHIVE_URL ?= https://github.com/allenai/asta-plugins/archive/$(ASTA_PLUGINS_REF).tar.gz

# The evidence extension is maintained with the workspace skill rather than
# vendored into every report. Replace it only after a complete download and
# extraction so a network failure cannot leave a partial extension behind.
workspace-assets:
	@set -eu; \
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
	trap cleanup 0 1 2 15; \
	curl -fsSL "$(ASTA_PLUGINS_ARCHIVE_URL)" -o "$$tmp/asta-plugins.tar.gz"; \
	tar -xzf "$$tmp/asta-plugins.tar.gz" -C "$$tmp"; \
	source_dir=$$(find "$$tmp" -type d -path '*/plugins/asta-tools/skills/workspace/assets/_extensions/evidence' -print -quit); \
	[ -n "$$source_dir" ] || { echo "evidence extension not found in asta-plugins@$(ASTA_PLUGINS_REF)" >&2; exit 1; }; \
	cp -R "$$source_dir" "$$tmp/evidence"; \
	mkdir -p _extensions; \
	mkdir "$$lock" 2>/dev/null || { echo "another workspace-assets install is in progress" >&2; exit 1; }; \
	lock_held=1; \
	if [ -e _extensions/evidence ] || [ -L _extensions/evidence ]; then \
		mv _extensions/evidence "$$backup"; \
	fi; \
	mv "$$tmp/evidence" _extensions/evidence

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
