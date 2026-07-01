# Workflow: submit

Copy the reflect report, conversation transcripts, and project artifacts into a new project-specific directory inside a clone of `allenai/asta-research-challenge`, then open a pull request.

This workflow takes user-visible actions (clone, push, PR open). Confirm the plan with the user before doing anything that mutates a remote.

## Preconditions

- `RESEARCH_CHALLENGE.md` exists in the current working directory. If not, route the user to **reflect** first.
- `git` and `gh` are installed and the user is authenticated (`gh auth status`). If `gh` is missing, stop and ask the user to install it — do not attempt to install it yourself.

## Inputs you need from the user (ask once, up front)

- **Project slug.** Default to the `project:` field in the `RESEARCH_CHALLENGE.md` frontmatter. Confirm with the user — this becomes the new directory name in the upstream repo, so it should be unique and descriptive (kebab-case).
- **Whether to include the full conversation transcript.** Default yes. Transcripts can be large and may contain incidental content; the user should consent.
- **Cursor users only.** If any of the work was done in Cursor, ask them to export their chats first: in Cursor, open the command palette (Cmd-Shift-P / Ctrl-Shift-P) → run **"Cursor: Export Chat"** → save the markdown files into `<PROJECT_DIR>/.cursor-chat/`. The transcript-copy script picks up that directory automatically. Reviewers can read the markdown directly on GitHub without any extra tooling. Skip this prompt if the user did not use Cursor.
- **Which artifacts to include.** Default to the list under `## Artifacts` in the report. Confirm before copying.

## Steps

### 1. Resolve paths

```bash
PROJECT_DIR=$(pwd)
PROJECT_SLUG=<from frontmatter or user>
```

Verify `RESEARCH_CHALLENGE.md` exists in `$PROJECT_DIR`.

Transcript source paths depend on which coding agent the user is running. Compute the candidates for all three; copy from whichever exist (the user may have used more than one):

| Agent | Path | Filter by cwd? |
|---|---|---|
| Claude Code | `~/.claude/projects/<ENCODED_CWD>/*.jsonl` | Path encodes cwd: `$(pwd \| sed 's\|/\|-\|g')`. |
| Codex CLI | `~/.codex/sessions/**/rollout-*.jsonl` | Organized by date, not cwd. Filter by the `cwd` field embedded in each rollout's first JSON record. |
| Cursor | `<PROJECT_DIR>/.cursor-chat/` | user-populated via Cursor's "Export Chat" command (see step 0 below) |

Warn the user if none of the candidates exist, but allow submission to proceed without transcripts.

### 2. Prepare a working clone of the upstream repo

Use a fresh temp directory so we never push from the user's project directory:

```bash
WORK=$(mktemp -d)
cd "$WORK"
gh repo clone allenai/asta-research-challenge
cd asta-research-challenge
BRANCH="add-$PROJECT_SLUG"
git checkout -b "$BRANCH"
```

If the directory `$PROJECT_SLUG/` already exists in the repo, stop and ask the user whether to overwrite, pick a new slug, or abort. Do not silently overwrite.

### 3. Copy the report

```bash
mkdir -p "$PROJECT_SLUG"
cp "$PROJECT_DIR/RESEARCH_CHALLENGE.md" "$PROJECT_SLUG/README.md"
```

The report is renamed to `README.md` so it renders on the directory's GitHub page. Keep the frontmatter intact.

### 4. Copy conversation transcripts (if user consented)

Run `scripts/copy-transcripts.sh` to detect and copy transcripts from Claude Code, Codex CLI, and Cursor in one pass:

```bash
scripts/copy-transcripts.sh "$PROJECT_DIR" "$PROJECT_SLUG/conversation"
```

Source locations probed (you don't need to compute these yourself; the script does):

| Agent | Source | Match strategy |
|---|---|---|
| Claude Code | `~/.claude/projects/<encoded-cwd>/*.jsonl` | path encodes cwd (slash→dash) |
| Codex CLI | `~/.codex/sessions/**/rollout-*.jsonl` | `cwd` field in each rollout's first record |
| Cursor | `~/Library/Application Support/Cursor/User/workspaceStorage/<hash>/` (macOS) · `~/.config/Cursor/User/workspaceStorage/<hash>/` (Linux) | `workspace.json` `folder` URI matches `file://$PROJECT_DIR` |

The script writes one block per agent to stdout in the form:

```
agent: claude-code
status: copied | none | unsupported
count: <n>           (only when copied)
path: <dest path>    (only when copied)
```

…and ends with `total_bytes: <n>`. Read those values:

- If every agent reports `status: none`, warn the user that no transcripts were found and confirm they still want to proceed.
- If `total_bytes` exceeds ~50 MB (≈ 52428800), warn the user and ask whether to truncate to the most recent sessions, drop one of the agent subdirectories, or skip transcripts entirely.

For Cursor, the script only copies what the user has already exported into `<PROJECT_DIR>/.cursor-chat/`. If `status: none` is reported and the user said they used Cursor, remind them to run **"Cursor: Export Chat"** and drop the markdown into that directory, then re-run submit. Do not try to read Cursor's `state.vscdb` SQLite directly — the schema shifts across versions and the output would not be reviewable on GitHub without extra tooling.

### 5. Copy project artifacts

Read the `## Artifacts` section of `$PROJECT_DIR/RESEARCH_CHALLENGE.md` and extract each listed path (strip leading bullets, backticks, and surrounding whitespace; resolve relative to `$PROJECT_DIR`). If the section is missing or empty, ask the user explicitly which paths to include before continuing.

Pipe the path list into `scripts/copy-artifacts.sh`:

```bash
printf '%s\n' "${ARTIFACT_PATHS[@]}" \
  | scripts/copy-artifacts.sh "$PROJECT_DIR" "$PROJECT_SLUG/artifacts"
```

The script applies these filters:

- Skips paths matched by the project's `.gitignore` (uses `git check-ignore` when `$PROJECT_DIR` is a git repo).
- Skips hard-coded excludes: `node_modules`, `.venv`, `venv`, `__pycache__`, `.git`, `.cache`, `.mypy_cache`, `.pytest_cache`, `.tox`, `.next`, `dist`, `build`, `target`.
- Skips any single file larger than 10 MB (override via `ASTA_RC_MAX_FILE_MB`).
- Aborts with exit 1 if the cumulative payload would exceed 100 MB (override via `ASTA_RC_MAX_TOTAL_MB`).

Output is one block per input path (`path:`, `status:`, plus `bytes:` or `reason:`) and a final `total_bytes:` line. Read those to decide what to surface:

- For each `status: skipped-too-large` — ask the user whether to re-run with `ASTA_RC_MAX_FILE_MB=<larger>` and include the file, or leave it out.
- If the script exits 1 (`status: aborted-total-limit`) — stop and ask the user how to slim down the artifact list (drop files, link out, compress) before retrying.
- If everything copied cleanly, summarize the count and total size to the user before moving on.

### 6. Stage, commit, push, and open the PR

```bash
git add "$PROJECT_SLUG"
git status   # show user what is being committed
```

Pause here and show the file list to the user for confirmation before pushing. Once they confirm:

```bash
git commit -m "Add $PROJECT_SLUG research challenge submission"
git push -u origin "$BRANCH"
gh pr create \
  --title "Add $PROJECT_SLUG" \
  --body "$(cat <<'EOF'
Submission generated by the research-challenge skill.

See README.md in the new directory for the project summary, self-critique, and skill-improvement suggestions.
EOF
)"
```

Return the PR URL to the user.

### 7. Clean up

The temp directory `$WORK` can be left in place (small) or removed:

```bash
cd "$PROJECT_DIR"
rm -rf "$WORK"
```

Only remove after the PR is created and the user has the URL.

## Failure modes to handle gracefully

- **`gh auth` fails.** Stop and ask the user to run `gh auth login` themselves (suggest they prefix with `!` in the prompt). Do not attempt to authenticate non-interactively.
- **Slug collision.** As in step 2 — ask, don't overwrite.
- **Push rejected.** Likely permission issue on the upstream. Tell the user; do not force-push.
- **PR creation fails.** Push succeeded but `gh pr create` did not — give the user the branch name and the URL to open the PR manually.

## Out of scope

- Merging the PR.
- Editing files in the upstream repo other than the new `$PROJECT_SLUG/` directory.
- Pushing or modifying anything in `$PROJECT_DIR` itself.
