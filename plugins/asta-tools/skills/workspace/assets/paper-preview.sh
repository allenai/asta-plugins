#!/usr/bin/env bash
set -euo pipefail

base=${1:-}
# Paper directory relative to the repo root; each holds its own main.tex.
dir=${2:-paper}
dir=${dir%/}
test -f "$dir/main.tex" || exit 0
mkdir -p "$dir/build" "_site/$dir"

export BIBINPUTS="$PWD:$PWD/$dir:${BIBINPUTS:-}"
export TEXINPUTS="$PWD/$dir:$PWD:${TEXINPUTS:-}"
# Preserve a configured engine; request a PDF when no rc selected one.
(cd "$dir" && latexmk -e '$pdf_mode ||= 1;' -recorder -deps-out=build/main.dep \
  -deps-escape=unix \
  -interaction=nonstopmode -halt-on-error -file-line-error -outdir=build main.tex)
if [ ! -f $dir/build/main.log ]; then
  echo "::error file=$dir/main.tex::LaTeX did not write $dir/build/main.log"
  exit 1
fi
if grep -Eiq 'Citation .+ undefined|There were undefined citations|Empty bibliography|Please \(re\)run Biber|No file .+\.bbl' $dir/build/main.log || \
   { [ -f $dir/build/main.blg ] && grep -Eiq 'no \\bibdata|didn.t find a database entry|couldn.t open database file|cannot find .+\.bib' $dir/build/main.blg; }; then
  echo "::error file=$dir/main.tex::Unresolved paper citations or missing bibliography"
  exit 1
fi
cp $dir/build/main.pdf _site/$dir/main.pdf
if [ -s $dir/build/main.bbl ]; then
  cp $dir/build/main.bbl _site/$dir/main.bbl
fi

convert_html() {
  local source=$1 target=$2 log=$3
  mkdir -p "$(dirname "$target")"
  if command -v latexmlc >/dev/null 2>&1 && \
     latexmlc --format=html5 --path="$PWD" --dest="$target" --log="$log" "$source" >/dev/null 2>&1 && \
     [ -s "$target" ] && [ -f "$log" ] && \
     ! grep -Eq '^Error:|Conversion complete: [1-9][0-9]* errors' "$log"; then
    return 0
  fi
  rm -f "$target"
  echo "::warning file=$source::LaTeXML conversion failed; see $log"
  return 1
}
convert_html "$dir/main.tex" "_site/$dir/html/index.html" "_site/$dir/html/latexml.log" || true

test -n "$base" || exit 0
fallback() {
  rm -f _site/$dir/preview.json _site/$dir/what-changed.pdf _site/$dir/diff-page-*.png
  printf '{"changed":true,"diff":false}\n' > _site/$dir/preview.json
  echo '::warning::Could not compare paper versions; the current paper PDF remains available'
}
if ! flags=$(python3 - "$base" "$dir" <<'PY'
import pathlib
import shlex
import subprocess
import sys

root = pathlib.Path.cwd().resolve()
paper_dir = root / sys.argv[2]
fls = paper_dir / "build/main.fls"
if not fls.is_file():
    raise SystemExit("LaTeX did not record paper inputs in build/main.fls")
inputs = set()
cwd = paper_dir
for line in fls.read_text(errors="replace").splitlines():
    if line.startswith("PWD "):
        cwd = pathlib.Path(line[4:])
    elif line.startswith("INPUT "):
        path = pathlib.Path(line[6:])
        path = (path if path.is_absolute() else cwd / path).resolve()
        try:
            inputs.add(path.relative_to(root).as_posix())
        except ValueError:
            pass

deps = paper_dir / "build/main.dep"
if not deps.is_file():
    raise SystemExit("LaTeX did not record paper dependencies in build/main.dep")
dep_text = "\n".join(
    line for line in deps.read_text(errors="replace").splitlines()
    if not line.lstrip().startswith("#")
).replace("\\\n", " ")
if ":" not in dep_text:
    raise SystemExit("LaTeX wrote an invalid paper dependency list")
for name in shlex.split(dep_text.partition(":")[2]):
    path = (paper_dir / name).resolve()
    try:
        inputs.add(path.relative_to(root).as_posix())
    except ValueError:
        pass

changed = subprocess.check_output(
    ["git", "diff", "--name-only", "-z", sys.argv[1], "HEAD"]
).decode().rstrip("\0").split("\0")
relevant = [
    path for path in changed
    if path in inputs or path in {"latexmkrc", ".latexmkrc", f"{sys.argv[2]}/latexmkrc", f"{sys.argv[2]}/.latexmkrc"}
]
print(int(any(path.startswith(sys.argv[2] + "/") and path.endswith(".tex") for path in relevant)),
      int(any(not (path.startswith(sys.argv[2] + "/") and path.endswith(".tex")) for path in relevant)))
PY
); then
  fallback
  exit 0
fi
read -r tex_changed other_changed <<< "$flags"
if [ "$tex_changed" = 0 ] && [ "$other_changed" = 0 ]; then exit 0; fi
printf '{"changed":true,"diff":false,"other_inputs":%s}\n' "$([ "$other_changed" = 1 ] && echo true || echo false)" > _site/$dir/preview.json

if ! git cat-file -e "$base:$dir/main.tex" 2>/dev/null; then
  printf '{"changed":true,"diff":false,"new":true}\n' > _site/$dir/preview.json
  exit 0
fi
if [ "$tex_changed" = 0 ]; then exit 0; fi
if ! old=$(mktemp -d); then fallback; exit 0; fi
if ! diff_tmp=$(mktemp $dir/what-changed.XXXXXXXX); then
  rm -rf "$old"
  fallback
  exit 0
fi
diff_tex="$diff_tmp.tex"
if ! mv "$diff_tmp" "$diff_tex"; then
  rm -f "$diff_tmp"
  rm -rf "$old"
  fallback
  exit 0
fi
diff_name=${diff_tex##*/}
diff_stem=${diff_name%.tex}
cleanup() {
  git worktree remove --force "$old" 2>/dev/null || true
  rm -rf "$old"
  rm -f "$diff_tex"
}
trap cleanup EXIT
if ! git worktree add --detach "$old" "$base" >/dev/null; then
  fallback
  exit 0
fi

if ! latexdiff --flatten "$old/$dir/main.tex" $dir/main.tex > "$diff_tex"; then
  echo '::warning::Could not build latexdiff PDF; the current paper PDF remains available'
  exit 0
fi
if ! python3 - "$diff_tex" <<'PY'
import pathlib
import re
import sys

body = pathlib.Path(sys.argv[1]).read_text(errors="replace").partition(r"\begin{document}")[2]
if not re.search(r"\\DIF(?:add|del)(?:begin|end)?(?:\{|\b)", body):
    raise SystemExit(1)
PY
then
  printf '{"changed":true,"diff":false,"other_inputs":%s,"unhighlighted":true}\n' "$([ "$other_changed" = 1 ] && echo true || echo false)" > _site/$dir/preview.json
  exit 0
fi
convert_html "$diff_tex" "_site/$dir/html/what-changed.html" \
  "_site/$dir/html/what-changed.log" || true
if (cd "$dir" && latexmk -e '$pdf_mode ||= 1;' -interaction=nonstopmode \
  -halt-on-error -file-line-error -outdir=build "$diff_name"); then
  cp "$dir/build/$diff_stem.pdf" _site/$dir/what-changed.pdf
  if ! pdftoppm -f 1 -l 12 -png -r 54 _site/$dir/what-changed.pdf _site/$dir/diff-page >/dev/null 2>&1; then
    rm -f _site/$dir/diff-page-*.png
    echo '::warning::Could not render paper diff thumbnails; the diff PDF remains available'
  fi
  pages=$(pdfinfo _site/$dir/what-changed.pdf 2>/dev/null | awk '/^Pages:/ {print $2; exit}') || pages=""
  if [[ "$pages" =~ ^[0-9]+$ ]]; then
    printf '{"changed":true,"diff":true,"other_inputs":%s,"thumbnail_limit":12,"page_count":%s}\n' "$([ "$other_changed" = 1 ] && echo true || echo false)" "$pages" > _site/$dir/preview.json
  else
    printf '{"changed":true,"diff":true,"other_inputs":%s,"thumbnail_limit":12}\n' "$([ "$other_changed" = 1 ] && echo true || echo false)" > _site/$dir/preview.json
  fi
else
  echo '::warning::Could not build latexdiff PDF; the current paper PDF remains available'
fi
