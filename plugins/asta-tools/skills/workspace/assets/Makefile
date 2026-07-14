.PHONY: preview render clean dev deployed-url check

preview:
	quarto preview --no-browser

render:
	quarto render

# Run the same quality gates CI runs, in one place so local and CI can't
# drift. CI's docs workflow calls this target — when a project grows a new
# gate, add it here (or as a prerequisite target), never as an inline workflow
# step. The shared render/validate logic is vendored in scripts/quarto-check.sh
# (from the workspace skill; update by re-copying, don't hand-edit).
check:
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
