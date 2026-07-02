---
name: save-work
description: Persist completed work. For each work/<slug>/README.md with status done, move it from Pending to Completed in project.md, index the README in work/index.yaml via asta-documents, and commit the artifacts to git. Use after one or more work items finish.
allowed-tools: Read(project.md) Read(work/**) Edit(project.md) Bash(git status) Bash(git add *) Bash(git diff *) Bash(git commit *) Bash(asta documents *) Skill(asta-tools:asta-documents)
---

# Save Work

Closes out finished work: updates `project.md`, indexes the work READMEs so they are searchable, and commits everything to git.

## Inputs

- `project.md` with Pending Work entries.
- One or more `work/<slug>/README.md` files with frontmatter `status: done`.

## Outputs

- `project.md` — finished items moved from Pending Work to Completed Work.
- `work/index.yaml` — one document entry per finished README, via `asta documents add`.
- A git commit containing the README, data artifacts, project.md update, and index.yaml update.

## Procedure

1. **Find finished items.** Scan `work/*/README.md` for frontmatter `status: done` that still appears under Pending Work in `project.md`.

2. **Index each one.** For each finished item:
   ```bash
   README_PATH="$(pwd)/work/<slug>/README.md"
   asta documents add "file://${README_PATH}" \
     --root work \
     --name="<one-line summary from project.md>" \
     --summary="<paste the Goal section's first paragraph>" \
     --tags="asta-assistant,work,<slug>" \
     --mime-type="text/markdown"
   ```
   If `work/index.yaml` does not exist yet, the first `asta documents add` will create it.

3. **Update `project.md`.** For each finished item, move its line from Pending Work to Completed Work. Drop the `(status: ...)` marker on the Completed Work line.

4. **Commit.** Skip if not working in a git repo. Stage and commit each file explicitly — do not use `git add -A`:
   ```bash
   git add project.md work/index.yaml work/<slug>/README.md work/<slug>/data
   git diff --cached --stat   # sanity-check what is being committed
   git commit -m "work(<slug>): <one-line summary>"
   ```
   Repeat per slug, or batch in one commit if several finished together — your judgment.

5. **Report.** Print the list of slugs that were saved and the resulting commit hash(es). Do not push.

## Out of scope

- Pushing to a remote.
- Deleting work directories (they remain on disk as the source of truth for the natural-language report).
- Modifying status of items that are not `done`.
