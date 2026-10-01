#!/usr/bin/env bash
set -euo pipefail

base=${1:-}
test -f paper/main.tex || exit 0
mkdir -p paper/build _site/paper

export BIBINPUTS="$PWD:$PWD/paper:${BIBINPUTS:-}"
export TEXINPUTS="$PWD/paper:$PWD:${TEXINPUTS:-}"
# Preserve a configured engine; request a PDF when no rc selected one.
(cd paper && latexmk -e '$pdf_mode ||= 1;' -recorder -deps-out=build/main.dep \
  -deps-escape=unix \
  -interaction=nonstopmode -halt-on-error -file-line-error -outdir=build main.tex)
cp paper/build/main.pdf _site/paper/main.pdf

test -n "$base" || exit 0
flags=$(python3 - "$base" <<'PY'
import pathlib
import shlex
import subprocess
import sys

root = pathlib.Path.cwd().resolve()
paper_dir = root / "paper"
fls = root / "paper/build/main.fls"
if not fls.is_file():
    raise SystemExit("LaTeX did not record paper inputs in paper/build/main.fls")
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

deps = root / "paper/build/main.dep"
if not deps.is_file():
    raise SystemExit("LaTeX did not record paper dependencies in paper/build/main.dep")
dep_text = deps.read_text(errors="replace").replace("\\\n", " ")
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
    if path in inputs or path in {"latexmkrc", "paper/latexmkrc"}
]
print(int(any(path.startswith("paper/") and path.endswith(".tex") for path in relevant)),
      int(any(not (path.startswith("paper/") and path.endswith(".tex")) for path in relevant)))
PY
)
read -r tex_changed other_changed <<< "$flags"
if [ "$tex_changed" = 0 ] && [ "$other_changed" = 0 ]; then exit 0; fi
printf '{"changed":true,"diff":false,"other_inputs":%s}\n' "$([ "$other_changed" = 1 ] && echo true || echo false)" > _site/paper/preview.json

if ! git cat-file -e "$base:paper/main.tex" 2>/dev/null; then
  printf '{"changed":true,"diff":false,"new":true}\n' > _site/paper/preview.json
  exit 0
fi
if [ "$tex_changed" = 0 ]; then exit 0; fi
old=$(mktemp -d)
diff_tex=$(mktemp paper/what-changed.XXXXXXXX.tex)
diff_name=${diff_tex##*/}
diff_stem=${diff_name%.tex}
cleanup() {
  git worktree remove --force "$old" 2>/dev/null || true
  rm -rf "$old"
  rm -f "$diff_tex"
}
trap cleanup EXIT
git worktree add --detach "$old" "$base" >/dev/null

if ! latexdiff --flatten "$old/paper/main.tex" paper/main.tex > "$diff_tex"; then
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
  printf '{"changed":true,"diff":false,"other_inputs":%s,"unhighlighted":true}\n' "$([ "$other_changed" = 1 ] && echo true || echo false)" > _site/paper/preview.json
  exit 0
fi
if (cd paper && latexmk -e '$pdf_mode ||= 1;' -interaction=nonstopmode \
  -halt-on-error -file-line-error -outdir=build "$diff_name"); then
  cp "paper/build/$diff_stem.pdf" _site/paper/what-changed.pdf
  if ! pdftoppm -f 1 -l 12 -png -r 54 _site/paper/what-changed.pdf _site/paper/diff-page >/dev/null 2>&1; then
    rm -f _site/paper/diff-page-*.png
    echo '::warning::Could not render paper diff thumbnails; the diff PDF remains available'
  fi
  printf '{"changed":true,"diff":true,"other_inputs":%s,"thumbnail_limit":12}\n' "$([ "$other_changed" = 1 ] && echo true || echo false)" > _site/paper/preview.json
else
  echo '::warning::Could not build latexdiff PDF; the current paper PDF remains available'
fi
