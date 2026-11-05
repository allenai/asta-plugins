#!/bin/sh
set -eu

site=${1:-_site}
if [ "${REQUIRE_WHAT_CHANGED:-false}" = true ] && [ ! -s "$site/what-changed.html" ]; then
  echo "missing What changed page: $site/what-changed.html" >&2
  exit 1
fi
paper="$site/paper-previews/paper"
if [ ! -s "$paper/main.pdf" ]; then
  echo "missing paper PDF: $paper/main.pdf" >&2
  exit 1
fi
if ! grep -q 'Vaswani' "$paper/main.bbl"; then
  echo "missing paper bibliography entry in $paper/main.bbl" >&2
  exit 1
fi
