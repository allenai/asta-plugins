#!/bin/sh
# Render the Quarto site and validate the output — the shared portion of the
# `make check` quality gates (project-specific gates live in the Makefile).
# Vendored verbatim from the asta-tools workspace skill: do not edit here;
# update by re-copying from the skill's assets.
set -u

# Structural evidence check first: it is fast, and a dangling `.ev` key is
# cheaper to report than to hunt for in render output. Judging whether a quote
# supports its claim is not scriptable — see the `check-claims` skill.
if [ -f scripts/check-evidence.py ]; then
  command -v python3 >/dev/null || {
    echo "check-evidence: python3 not found" >&2
    exit 1
  }
  python3 scripts/check-evidence.py || exit 1
fi

rm -f _site/index.html  # stale output must not satisfy the checks below

# Stream the render through tee but keep quarto's exit code (a plain pipe
# would return tee's, letting a partial render pass; POSIX sh, no pipefail).
{ quarto render 2>&1; echo $? > quarto-render.status; } | tee quarto-render.log
st=$(cat quarto-render.status)
rm -f quarto-render.status
if [ "$st" -ne 0 ]; then
  echo "::error::quarto render failed (exit $st)"
  exit "$st"
fi

if [ ! -f _site/index.html ]; then
  echo "::error::Quarto render failed — _site/index.html not found"
  exit 1
fi

# Fail on Quarto warnings (broken citations, dead links, etc.), surfacing them
# in the CI step summary when available.
warnings=$(sed 's/\x1b\[[0-9;]*m//g' quarto-render.log | grep -E '\[WARNING\]|^WARN:' || true)
if [ -n "$warnings" ]; then
  echo "::error::Quarto warnings found (broken citations, dead links, etc.):"
  echo "$warnings"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    { echo "## ⚠️ Quarto warnings"; echo '```'; echo "$warnings"; echo '```'; } >> "$GITHUB_STEP_SUMMARY"
  fi
  exit 1
fi

echo "✓ quarto render OK (no warnings)"
