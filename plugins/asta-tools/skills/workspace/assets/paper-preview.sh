#!/usr/bin/env bash
set -euo pipefail

base=${1:-}
test -f paper/main.tex || exit 0
mkdir -p paper/build _site/paper

export BIBINPUTS="$PWD:$PWD/paper:${BIBINPUTS:-}"
export TEXINPUTS="$PWD/paper:$PWD:${TEXINPUTS:-}"
(cd paper && latexmk -pdf -interaction=nonstopmode -halt-on-error -file-line-error -outdir=build main.tex)
cp paper/build/main.pdf _site/paper/main.pdf

test -n "$base" || exit 0
if git diff --quiet "$base" HEAD -- paper references.bib; then exit 0; fi
printf '{"changed":true,"diff":false}\n' > _site/paper/preview.json

if ! git cat-file -e "$base:paper/main.tex" 2>/dev/null; then
  printf '{"changed":true,"diff":false,"new":true}\n' > _site/paper/preview.json
  exit 0
fi
old=$(mktemp -d)
cleanup() {
  git worktree remove --force "$old" 2>/dev/null || true
  rm -rf "$old"
  rm -f paper/what-changed.tex
}
trap cleanup EXIT
git worktree add --detach "$old" "$base" >/dev/null

if latexdiff --flatten "$old/paper/main.tex" paper/main.tex > paper/what-changed.tex \
  && (cd paper && latexmk -pdf -interaction=nonstopmode -halt-on-error -file-line-error -outdir=build what-changed.tex); then
  cp paper/build/what-changed.pdf _site/paper/what-changed.pdf
  if ! pdftoppm -png -r 54 _site/paper/what-changed.pdf _site/paper/diff-page >/dev/null 2>&1; then
    rm -f _site/paper/diff-page-*.png
    echo '::warning::Could not render paper diff thumbnails; the diff PDF remains available'
  fi
  printf '{"changed":true,"diff":true}\n' > _site/paper/preview.json
else
  echo '::warning::Could not build latexdiff PDF; the current paper PDF remains available'
fi
