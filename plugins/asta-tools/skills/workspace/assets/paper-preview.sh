#!/usr/bin/env bash
set -euo pipefail

base=${1:-}
# Paper directory relative to the repo root. Its main document is main.tex, or
# else the single top-level .tex file containing \documentclass.
dir=${2:-paper}
dir=${dir%/}
site_dir="_site/paper-previews/$dir"
if [[ -z "$dir" || "$dir" == /* || "$dir" == *//* || "$dir" =~ (^|/)(\.{1,2}|-[^/]*)(/|$) || "$dir" =~ [[:cntrl:]] ]]; then
  echo "::error::Paper directory must be a safe relative path"
  exit 1
fi
find_main() {
  local found=() file
  if [ -f "$1/main.tex" ] && [ ! -L "$1/main.tex" ]; then echo main.tex; return 0; fi
  for file in "$1"/*.tex; do
    [ -f "$file" ] && [ ! -L "$file" ] && python3 -c 'import pathlib,re,sys; sys.exit(not re.search(r"(?m)^[^%\n]*\\documentclass\s*[\[{]", re.sub(r"%[^\n]*", "", pathlib.Path(sys.argv[1]).read_text(errors="replace"))))' "$file" && found+=("${file##*/}")
  done
  if [ "${#found[@]}" -gt 1 ]; then
    echo "::warning::${2:-$1} has several .tex files with \\documentclass: ${found[*]}; add main.tex to choose one" >&2
  fi
  [ "${#found[@]}" -eq 1 ] && echo "${found[0]}"
}
main=$(find_main "$dir") || exit 0
stem=${main%.tex}
mkdir -p "$dir/build" "$site_dir"
printf '{"changed":false}\n' > "$site_dir/preview.json"

# Overleaf can't see the repo root, so a synced paper must build without it.
if [ -f "$dir/overleaf.json" ]; then
  export BIBINPUTS="$PWD/$dir:${BIBINPUTS:-}"
  export TEXINPUTS="$PWD/$dir:${TEXINPUTS:-}"
else
  export BIBINPUTS="$PWD:$PWD/$dir:${BIBINPUTS:-}"
  export TEXINPUTS="$PWD/$dir:$PWD:${TEXINPUTS:-}"
fi
# Preserve a configured engine; request a PDF when no rc selected one.
# -e runs after rc files: override their escaping for this private dependency file.
(cd "$dir" && latexmk -e '$pdf_mode ||= 1; $deps_escape = "none";' -recorder -deps-out="build/$stem.dep" \
  -interaction=nonstopmode -halt-on-error -file-line-error -outdir=build "$main")
if [ ! -f "$dir/build/$stem.log" ]; then
  echo "::error file=$dir/$main::LaTeX did not write $dir/build/$stem.log"
  exit 1
fi
if grep -Eiq 'Citation .+ undefined|There were undefined citations|Empty bibliography|Please \(re\)run Biber|No file .+\.bbl' "$dir/build/$stem.log" || \
   { [ -f "$dir/build/$stem.blg" ] && grep -Eiq 'no \\bibdata|didn.t find a database entry|couldn.t open database file|cannot find .+\.bib' "$dir/build/$stem.blg"; }; then
  echo "::error file=$dir/$main::Unresolved paper citations or missing bibliography"
  exit 1
fi
cp "$dir/build/$stem.pdf" "$site_dir/main.pdf"
if [ -s "$dir/build/$stem.bbl" ]; then
  cp "$dir/build/$stem.bbl" "$site_dir/main.bbl"
fi

convert_html() (
  local source=$1 target=$2 log=$3
  local output="${log}.output" result=1 input="$source" prepared_dir="" diff=${4:-false}
  trap 'if [ -n "$prepared_dir" ]; then rm -rf "$prepared_dir"; fi' EXIT
  mkdir -p "$(dirname "$target")"
  # Quarto's PDF preamble loads packages that only affect PDF navigation and
  # table footnotes. LaTeXML can spend minutes parsing their expl3 internals.
  if [ "$diff" = true ] || grep -Fq 'pdfcreator={LaTeX via pandoc}' "$source"; then
    if prepared_dir=$(mktemp -d); then
      if python3 - "$source" "$prepared_dir/$(basename "$source")" "$diff" <<'PY'
import pathlib
import re
import sys

source = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
if "pdfcreator={LaTeX via pandoc}" in source:
    source = source.replace(r"\usepackage{bookmark}", r"\usepackage{hyperref}")
    source = source.replace(
        r"\IfFileExists{footnotehyper.sty}{\usepackage{footnotehyper}}{\usepackage{footnote}}",
        "",
    )
    source = source.replace(r"\makesavenoteenv{longtable}", "")
if sys.argv[3] == "true":
    # Preserve latexdiff's macros, but identify their output without color heuristics.
    # latexdiff supplies ordinary one-argument macros via \providecommand.
    markers = r"""\RequirePackage{latexml}
\ifdefined\DIFadd
\let\astadiffadd\DIFadd
\renewcommand{\DIFadd}[1]{\lxWithClass{asta-diff-add}{\astadiffadd{#1}}}
\fi
\ifdefined\DIFdel
\let\astadiffdel\DIFdel
\renewcommand{\DIFdel}[1]{\lxWithClass{asta-diff-del}{\astadiffdel{#1}}}
\fi
"""
    source, count = re.subn(
        r"(?m)^[ \t]*\\begin\{document\}",
        lambda match: markers + match.group(),
        source,
        count=1,
    )
    if not count:
        raise SystemExit("No document start for LaTeXML diff markers")
pathlib.Path(sys.argv[2]).write_text(source, encoding="utf-8")
PY
      then
        input="$prepared_dir/$(basename "$source")"
        local bbl="$(dirname "$source")/build/$(basename "${source%.tex}").bbl"
        if [ -f "$bbl" ]; then
          ln -s "$PWD/$bbl" "$prepared_dir/$(basename "${source%.tex}").bbl" || \
            echo "::warning file=$source::Could not link the compiled bibliography for LaTeXML"
        fi
      else
        echo "::warning file=$source::Could not prepare Quarto TeX for LaTeXML; trying the original"
      fi
    else
      echo "::warning file=$source::Could not create a temporary TeX directory; trying the original"
    fi
  fi
  if command -v latexmlc >/dev/null 2>&1; then
    if timeout --kill-after=15s 180s latexmlc --format=html5 --path=. \
        --path="$(dirname "$source")" --dest="$target" --log="$log" "$input" >"$output" 2>&1; then
      result=0
    else
      result=$?
    fi
  else
    printf 'latexmlc is not installed\n' > "$log"
  fi
  if [ -s "$output" ]; then cat "$output" >> "$log"; fi
  if [ "$result" -eq 124 ]; then echo "LaTeXML timed out after 180 seconds" >> "$log"; fi
  rm -f "$output"
  if [ "$result" -eq 0 ] && [ -s "$target" ] && [ -f "$log" ] && \
     ! grep -Eq '^Error:|Conversion complete: [1-9][0-9]* errors?' "$log" && \
     python3 - "$target" "$diff" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
document = path.read_text(encoding="utf-8")
head = re.search(r"<head(?:\s[^>]*)?>", document, flags=re.IGNORECASE)
if not head:
    raise SystemExit("LaTeXML HTML has no head for a content security policy")
policy = (
    "default-src 'none'; img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
    "script-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"
)
meta = f'<meta http-equiv="Content-Security-Policy" content="{policy}">'
document = document[:head.end()] + meta + document[head.end():]
if sys.argv[2] == "true":
    # The sandboxed iframe cannot load LaTeXML's linked stylesheets.
    style = """<style>
.asta-diff-add { background: #d7f5dd; color: #032b13 !important;
  text-decoration: none; border-radius: 2px; }
.asta-diff-del { background: #ffd7d5; color: #40100c !important;
  text-decoration: line-through; text-decoration-color: #cf222e; border-radius: 2px; }
.asta-diff-add [style], .asta-diff-add [mathcolor],
.asta-diff-del [style], .asta-diff-del [mathcolor] { color: inherit !important; }
</style>"""
    end = re.search(r"</head\s*>", document, flags=re.IGNORECASE)
    if not end:
        raise SystemExit("LaTeXML HTML has no closing head for the diff palette")
    document = document[:end.start()] + style + document[end.start():]
path.write_text(document, encoding="utf-8")
PY
  then
    return 0
  fi
  rm -f "$target"
  echo "::warning file=$source::LaTeXML conversion failed; see $log"
  return 1
)
convert_html "$dir/$main" "$site_dir/html/index.html" "$site_dir/html/latexml.log" || true

test -n "$base" || exit 0
fallback() {
  rm -f "$site_dir/preview.json" "$site_dir/what-changed.pdf" "$site_dir"/diff-page-*.png
  printf '{"changed":true,"diff":false}\n' > "$site_dir/preview.json"
  echo '::warning::Could not compare paper versions; the current paper PDF remains available'
}
if ! flags=$(python3 - "$base" "$dir" "$stem" <<'PY'
import pathlib
import subprocess
import sys

root = pathlib.Path.cwd().resolve()
paper_dir = root / sys.argv[2]
fls = paper_dir / f"build/{sys.argv[3]}.fls"
if not fls.is_file():
    raise SystemExit(f"LaTeX did not record paper inputs in {fls}")
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

deps = paper_dir / f"build/{sys.argv[3]}.dep"
if not deps.is_file():
    raise SystemExit(f"LaTeX did not record paper dependencies in {deps}")
expect_target = True
seen_target = False
# Latexmk indents each unescaped pathname by four spaces. Multiple output
# formats and optional phony rules can produce more than one target.
# A final pathname ending in a backslash is ambiguous and uses the fallback.
for line in deps.read_text(errors="replace").splitlines():
    if not line or line.startswith("#"):
        continue
    continued = line.endswith("\\")
    entry = line[:-1] if continued else line
    if expect_target:
        if not entry.endswith(" :"):
            raise SystemExit("LaTeX wrote an invalid paper dependency target")
        seen_target = True
    else:
        if not entry.startswith("    ") or not entry[4:]:
            raise SystemExit("LaTeX wrote an invalid paper dependency path")
        name = entry[4:]
        path = (paper_dir / name).resolve()
        try:
            inputs.add(path.relative_to(root).as_posix())
        except ValueError:
            pass
    expect_target = not continued
if not seen_target or not expect_target:
    raise SystemExit("LaTeX wrote an incomplete paper dependency list")

changed = subprocess.check_output(
    ["git", "diff", "--name-only", "-z", sys.argv[1], "HEAD"]
).decode().rstrip("\0").split("\0")
relevant = [
    path for path in changed
    # A removed top-level source can change the selected main without changing its inputs.
    if path in inputs or (pathlib.PurePosixPath(path).parent == pathlib.PurePosixPath(sys.argv[2]) and path.endswith(".tex")) or path in {"latexmkrc", ".latexmkrc", f"{sys.argv[2]}/latexmkrc", f"{sys.argv[2]}/.latexmkrc"}
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
printf '{"changed":true,"diff":false,"other_inputs":%s}\n' "$([ "$other_changed" = 1 ] && echo true || echo false)" > "$site_dir/preview.json"

if ! git ls-tree -z --name-only "$base" -- "$dir/" 2>/dev/null | tr '\0' '\n' | grep -q '\.tex$'; then
  printf '{"changed":true,"diff":false,"new":true}\n' > "$site_dir/preview.json"
  exit 0
fi
if [ "$tex_changed" = 0 ]; then exit 0; fi
if ! old=$(mktemp -d); then fallback; exit 0; fi
if ! diff_tmp=$(mktemp "$dir/what-changed.XXXXXXXX"); then
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

# The base may name its main document differently, e.g. a main.tex shim.
if ! old_main=$(find_main "$old/$dir" "$dir at base $base"); then
  printf '{"changed":true,"diff":false,"new":true}\n' > "$site_dir/preview.json"
  exit 0
fi
if ! latexdiff --flatten "$old/$dir/$old_main" "$dir/$main" > "$diff_tex"; then
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
  printf '{"changed":true,"diff":false,"other_inputs":%s,"unhighlighted":true}\n' "$([ "$other_changed" = 1 ] && echo true || echo false)" > "$site_dir/preview.json"
  exit 0
fi
html_diff=false
if convert_html "$diff_tex" "$site_dir/html-diff/index.html" \
  "$site_dir/html-diff/latexml.log" true; then
  html_diff=true
fi
if (cd "$dir" && latexmk -e '$pdf_mode ||= 1;' -interaction=nonstopmode \
  -halt-on-error -file-line-error -outdir=build "$diff_name"); then
  cp "$dir/build/$diff_stem.pdf" "$site_dir/what-changed.pdf"
  if ! pdftoppm -f 1 -l 12 -png -r 54 "$site_dir/what-changed.pdf" "$site_dir/diff-page" >/dev/null 2>&1; then
    rm -f "$site_dir"/diff-page-*.png
    echo '::warning::Could not render paper diff thumbnails; the diff PDF remains available'
  fi
  pages=$(pdfinfo "$site_dir/what-changed.pdf" 2>/dev/null | awk '/^Pages:/ {print $2; exit}') || pages=""
  if [[ "$pages" =~ ^[0-9]+$ ]]; then
    printf '{"changed":true,"diff":true,"html_diff":%s,"other_inputs":%s,"thumbnail_limit":12,"page_count":%s}\n' "$html_diff" "$([ "$other_changed" = 1 ] && echo true || echo false)" "$pages" > "$site_dir/preview.json"
  else
    printf '{"changed":true,"diff":true,"html_diff":%s,"other_inputs":%s,"thumbnail_limit":12}\n' "$html_diff" "$([ "$other_changed" = 1 ] && echo true || echo false)" > "$site_dir/preview.json"
  fi
else
  printf '{"changed":true,"diff":false,"html_diff":%s,"other_inputs":%s}\n' "$html_diff" "$([ "$other_changed" = 1 ] && echo true || echo false)" > "$site_dir/preview.json"
  echo '::warning::Could not build latexdiff PDF; the current paper PDF remains available'
fi
