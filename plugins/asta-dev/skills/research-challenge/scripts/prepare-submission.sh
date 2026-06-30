#!/usr/bin/env bash
# prepare-submission.sh — assemble a research-challenge submission in a temp
# clone of the upstream challenge repo. Stops *before* any remote mutation
# (no git push, no gh pr create) so a human can review and confirm.
#
# Pipes:
#   1. mktemp -d a work dir, gh repo clone the upstream into it.
#   2. Check out a new branch  add-<slug>  off the default branch.
#   3. Verify the upstream does not already contain a <slug>/ directory.
#   4. Copy <PROJECT_DIR>/RESEARCH_CHALLENGE.md → <slug>/README.md.
#   5. Invoke copy-transcripts.sh "<PROJECT_DIR>" "<slug>/conversation".
#   6. Parse "## Artifacts" in the report, extract each bullet of the form
#      `- \`<path>\` …`, existence-filter, and pipe through copy-artifacts.sh
#      → "<slug>/artifacts".
#   7. git add the slug dir; print git status and the next commands the
#      caller should run after review (commit / push / pr create).
#
# Usage:
#   prepare-submission.sh PROJECT_DIR [--slug SLUG] [--upstream OWNER/REPO]
#
# Defaults:
#   SLUG     → frontmatter `project:` field in RESEARCH_CHALLENGE.md
#   UPSTREAM → allenai/asta-research-challenge
#
# Output (stdout, key: value lines):
#   work_dir:        <path to the temp clone>
#   branch:          add-<slug>
#   slug:            <slug>
#   report:          copied
#   transcripts:     <copied total_bytes> | none
#   artifacts:       <copied count, total_bytes> | empty
#   staged_files:    <n>
#   next:            (a multi-line block of suggested commands)
#
# Exit codes:
#   0  staged and ready for the caller to commit/push
#   2  bad args / missing inputs
#   3  slug collides upstream (caller must pick a new slug or overwrite)
#   4  copy-artifacts.sh aborted (size budget exceeded)
#   5  gh not authenticated
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PROJECT_DIR=""
SLUG=""
UPSTREAM="allenai/asta-research-challenge"

while [ $# -gt 0 ]; do
  case "$1" in
    --slug)     SLUG="$2"; shift 2 ;;
    --upstream) UPSTREAM="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    -*)
      echo "prepare-submission: unknown flag '$1'" >&2; exit 2 ;;
    *)
      if [ -z "$PROJECT_DIR" ]; then
        PROJECT_DIR="$1"
      else
        echo "prepare-submission: unexpected positional arg '$1'" >&2; exit 2
      fi
      shift ;;
  esac
done

if [ -z "$PROJECT_DIR" ]; then
  echo "usage: prepare-submission.sh PROJECT_DIR [--slug SLUG] [--upstream OWNER/REPO]" >&2
  exit 2
fi
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"

REPORT="$PROJECT_DIR/RESEARCH_CHALLENGE.md"
if [ ! -f "$REPORT" ]; then
  echo "prepare-submission: $REPORT not found — run the reflect workflow first" >&2
  exit 2
fi

if [ -z "$SLUG" ]; then
  SLUG=$(awk '/^---$/{c++; next} c==1 && /^project:/{sub(/^project:[[:space:]]*/, ""); print; exit}' "$REPORT" || true)
fi
if [ -z "$SLUG" ]; then
  echo "prepare-submission: could not derive slug from RESEARCH_CHALLENGE.md frontmatter; pass --slug" >&2
  exit 2
fi

if ! command -v gh >/dev/null; then
  echo "prepare-submission: 'gh' not found on PATH — install GitHub CLI first" >&2
  exit 2
fi
if ! gh auth status >/dev/null 2>&1; then
  echo "prepare-submission: gh is not authenticated — run 'gh auth login' first" >&2
  exit 5
fi

# Slug-collision check on upstream (404 means free).
if gh api "repos/$UPSTREAM/contents/$SLUG" >/dev/null 2>&1; then
  echo "prepare-submission: $UPSTREAM already contains a '$SLUG/' directory; pick a new slug or remove it upstream" >&2
  exit 3
fi

WORK=$(mktemp -d -t research-challenge-submission.XXXXXX)
cleanup_on_err() { rm -rf "$WORK"; }
trap cleanup_on_err ERR

cd "$WORK"
gh repo clone "$UPSTREAM" >/dev/null 2>&1
REPO_DIR="$WORK/$(basename "$UPSTREAM")"
cd "$REPO_DIR"

BRANCH="add-$SLUG"
git checkout -b "$BRANCH" >/dev/null 2>&1

# 4. Copy report → README.md
mkdir -p "$SLUG"
cp "$REPORT" "$SLUG/README.md"

# 5. Transcripts
transcripts_total=0
if [ -x "$SCRIPT_DIR/copy-transcripts.sh" ]; then
  tc_out=$("$SCRIPT_DIR/copy-transcripts.sh" "$PROJECT_DIR" "$SLUG/conversation")
  transcripts_total=$(printf '%s\n' "$tc_out" | awk '/^total_bytes:/{print $2; exit}')
fi
transcripts_total=${transcripts_total:-0}

# 6. Artifacts: extract bullet paths from the "## Artifacts" section.
# Pattern: lines starting with `- \`<path>\`` (path is the first content of the bullet).
ARTIFACT_PATHS=$(awk '
  /^## Artifacts[[:space:]]*$/ { inside=1; next }
  /^## / && inside { exit }
  inside { print }
' "$REPORT" \
  | sed -nE 's/^- `([^`]+)`.*/\1/p' \
  | awk '!seen[$0]++')

artifact_count=0
artifact_bytes=0
artifact_status="empty"
if [ -n "$ARTIFACT_PATHS" ]; then
  # Existence-filter and drop the report itself (it's already README.md).
  filtered=""
  while IFS= read -r p; do
    [ -z "$p" ] && continue
    [ "$p" = "RESEARCH_CHALLENGE.md" ] && continue
    if [ -e "$PROJECT_DIR/$p" ]; then
      filtered="$filtered$p"$'\n'
    fi
  done <<< "$ARTIFACT_PATHS"

  if [ -n "$filtered" ]; then
    set +e
    ca_out=$(printf '%s' "$filtered" | "$SCRIPT_DIR/copy-artifacts.sh" "$PROJECT_DIR" "$SLUG/artifacts")
    ca_rc=$?
    set -e
    if [ $ca_rc -eq 1 ]; then
      echo "$ca_out" >&2
      echo "prepare-submission: copy-artifacts aborted (size budget); slim the Artifacts list and retry" >&2
      exit 4
    fi
    artifact_bytes=$(printf '%s\n' "$ca_out" | awk '/^total_bytes:/{print $2; exit}')
    artifact_count=$(printf '%s\n' "$ca_out" | awk '/^status: copied$/{c++} END{print c+0}')
    artifact_status="copied"
  fi
fi

# 7. Stage and report.
git add "$SLUG" >/dev/null
staged_count=$(git diff --cached --name-only | wc -l | tr -d ' ')

cat <<EOF
work_dir:        $REPO_DIR
branch:          $BRANCH
slug:            $SLUG
report:          copied
transcripts:     ${transcripts_total:-0} bytes
artifacts:       $artifact_status ($artifact_count files, $artifact_bytes bytes)
staged_files:    $staged_count

--- git status ---
$(git status --short)

--- next commands ---
cd "$REPO_DIR"
git commit -m "Add $SLUG research challenge submission"
git push -u origin "$BRANCH"
gh pr create \\
  --title "Add $SLUG" \\
  --body "Submission generated by the research-challenge skill. See README.md in the new directory."
EOF

# Disarm the err-cleanup trap so the workdir survives for the caller to push from.
trap - ERR
