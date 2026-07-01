#!/usr/bin/env bash
# Warm the asta-documents search cache by running an initial broad query.
#
# The first search after indexing builds internal BM25 + embedding indexes.
# This script triggers that build so subsequent searches are fast.
#
# Usage:
#   ./warm-cache.sh <index-root>
#
# Arguments:
#   index-root      Root directory containing index.yaml
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <index-root>" >&2
  exit 1
fi

INDEX_ROOT="$1"

echo "Index root: $INDEX_ROOT"
echo "This may take 5-30 seconds (builds BM25 + embedding index)..."
echo

asta documents --root "$INDEX_ROOT" search --summary="research" > /dev/null 2>&1 || true

echo "Cache warmed. Subsequent searches will be fast."
echo
echo "Try:"
echo "  asta documents --root \"$INDEX_ROOT\" search --summary=\"your query\""
