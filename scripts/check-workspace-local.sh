#!/usr/bin/env bash
set -euo pipefail
export GITHUB_WORKSPACE="${GITHUB_WORKSPACE:-$(pwd)}"
export GITHUB_SHA="${GITHUB_SHA:-$(git rev-parse HEAD)}"
export ASTA_WORKSPACE_RESOLVED_SHA="$GITHUB_SHA"
export ASTA_WORKSPACE_RESOLVED_REPOSITORY="${ASTA_WORKSPACE_RESOLVED_REPOSITORY:-allenai/asta-plugins}"
cd examples/workspace
set -euo pipefail
git config --global --add safe.directory "$GITHUB_WORKSPACE"
uv tool install --force ../..
export PATH="$(uv tool dir --bin):$PATH"
# Start cold: the example must fetch its own managed rules and extensions.
rm -rf .asta/cache _extensions
make check
test -f .asta/cache/workspace.mk
test -f _extensions/asta-theme/light.scss
test -f _extensions/evidence/snippet.lua
test -f _extensions/asta-slides/_extension.yml
# Verify the resolved source, not just the requested workflow pin.
python3 -c 'import json, os; from pathlib import Path; state = json.loads(Path(".asta/cache/workspace.json").read_text()); assert state["source_ref"] == os.environ["GITHUB_SHA"], state; assert Path(".asta/cache/workspace.mk").read_bytes().endswith(Path("../../plugins/asta-tools/skills/workspace/assets/workspace.mk").read_bytes())'
for extension in asta-theme evidence asta-slides; do
  diff -r "../../plugins/asta-tools/skills/workspace/assets/_extensions/$extension" "_extensions/$extension"
done
git check-ignore .asta/cache/workspace.mk _extensions/asta-theme/light.scss
make preview-artifact-check
git diff --exit-code  # prints any tracked file a build or sync modified

set -euo pipefail
uv tool install --force ../..
# The image ships a released asta; run the one just built from this checkout.
export PATH="$(uv tool dir --bin):$PATH"
test "$(command -v asta)" = "$(uv tool dir --bin)/asta"
# Only acceptance tests need a browser; the CLI compares live decks without one.
uv run --no-project --with playwright==1.64.1 python -m playwright install --with-deps chromium >/dev/null
uv run --no-project --with playwright==1.64.1 python ../../tests/browser/local-what-changed.py . ../../tests/browser/artifacts
git diff --exit-code  # prints any tracked file a build or sync modified

