#!/bin/sh
# Render the Quarto site and validate the output — the shared portion of the
# `make check` quality gates (project-specific gates live in the Makefile).
# Vendored verbatim from the asta-tools workspace skill: do not edit here;
# update by re-copying from the skill's assets.
set -u

# Reject unresolved paper conflicts on every PR, before any rendering.
if ! command -v python3 >/dev/null 2>&1; then
  echo "::error::python3 is required to check paper conflicts; install Python 3 and retry."
  exit 1
fi
python3 - <<'CHECK_PAPER' || exit 1
import os, pathlib, re, stat, subprocess, sys
# Match overleaf_sync.conflict_files: known text sources, never binary assets.
suffixes = {".tex", ".ltx", ".bib", ".bst", ".bbx", ".cbx", ".sty", ".cls",
            ".clo", ".def", ".cfg", ".dtx", ".ins", ".tikz", ".pgf", ".csv",
            ".tsv", ".dat", ".txt", ".md"}
result = subprocess.run(["git", "ls-files", "-z"], capture_output=True)
if result.returncode:
    print("Cannot inspect paper conflicts; run make check in the workspace Git checkout.")
    sys.exit(1)
paths = [pathlib.Path(os.fsdecode(name)) for name in result.stdout.split(b"\0") if name]
roots = {p.parent for p in paths if p.name in {"latexmkrc", ".latexmkrc"}}
# A paired paper's record lives at .asta/overleaf/<paper dir>.json.
records = pathlib.Path(".asta/overleaf")
roots |= {p.relative_to(records).with_suffix("") for p in paths
          if records in p.parents and p.suffix == ".json"}
marker = re.compile(rb"^(?:<<<<<<<|>>>>>>>|\|{7})(?:[ \t]|\r?\n?\Z)")
separator = re.compile(rb"^=======\r?\n?\Z")
base = os.path.realpath(".")


def marked(path, separators):
    # Stream bounded lines so a large tracked file cannot exhaust memory.
    start = True
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        while line := stream.readline(65536):
            if b"\0" in line:
                return False
            if start and (marker.match(line) or (separators and separator.match(line))):
                return True
            start = line.endswith(b"\n")
    return False


failed, unsafe = [], []
for path in paths:
    if (path.suffix.lower() in suffixes
            and any(root == path.parent or root in path.parents for root in roots)):
        full = os.path.join(base, path)
        if not os.path.lexists(full):
            continue
        # Never follow a tracked symlink or symlinked directory out of the checkout.
        if (os.path.realpath(full) != os.path.normpath(full)
                or not stat.S_ISREG(os.lstat(full).st_mode)):
            unsafe.append(str(path))
        elif marked(full, path.suffix.lower() not in {".md", ".txt"}):
            failed.append(str(path))
if unsafe:
    print("Paper sources must be regular files inside the checkout, not symlinks: " + ", ".join(unsafe))
if failed:
    print("Unresolved paper conflict markers: " + ", ".join(failed))
if unsafe or failed:
    sys.exit(1)
CHECK_PAPER

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
