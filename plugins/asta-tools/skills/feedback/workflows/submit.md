# Workflow: submit

Upload a reviewed feedback submission directory to the Asta team using `asta feedback submit`.

This workflow takes a user-visible action (it uploads the bundle). Confirm the contents with the user before uploading.

## Preconditions

- A submission directory exists with a `FEEDBACK.md` at its root. If not, route the user to **interview** first.
- The user is authenticated to Asta.

## Inputs

- **`DIR`** — the submission directory (default to the one **interview** just wrote, `<project-root>/.asta/feedback/<slug>/`). Confirm with the user.

## Steps

### 1. Check auth

```bash
asta auth status
```

If not authenticated, ask the user to run `asta auth login` (suggest prefixing with `!` so it runs in this session), then continue. Do not attempt to authenticate non-interactively.

### 2. Review the bundle (dry run)

Show the user exactly what will be sent — the manifest, with no network upload:

```bash
asta feedback submit --dry-run "$DIR"
```

This prints the file list, sizes, and content types. Read it back to the user and confirm:

- The narrative reads the way they want (offer to re-open `FEEDBACK.md` for edits).
- The supporting files are the intended ones — nothing sensitive or oversized slipped in.

If the command errors (missing `FEEDBACK.md`, a per-file or total size gate), fix it with the user: edit the narrative, drop or slim a file, or — only if a large file is genuinely wanted — re-run with `ASTA_FEEDBACK_MAX_FILE_MB` / `ASTA_FEEDBACK_MAX_TOTAL_MB` raised. Do not paper over an accidental large file by raising the limit.

### 3. Submit

Once the user confirms:

```bash
asta feedback submit "$DIR"
```

The command bundles the directory, asks the Gateway for a submission id and a presigned upload URL, uploads the bundle, and prints:

```
✅ Feedback submitted. Submission id: <id>
```

### 4. Report back

Give the user the submission id and confirm it's sent. The local directory stays in place under `.asta/feedback/` — mention they can delete it or keep it for their own records.

## Failure modes to handle gracefully

- **Not authenticated / token expired.** `asta feedback submit` will fail on auth. Route the user to `asta auth login`; do not retry blindly.
- **Size gate exceeded.** The dry run (step 2) surfaces this before any upload — handle it there.
- **Upload fails after the id is minted.** Report the error and offer to re-run `asta feedback submit "$DIR"`; the command is safe to retry (it mints a fresh submission).

## Out of scope

- Editing the report content — that is **interview** (or a quick `Edit` the user requests).
- Opening GitHub issues/PRs.
