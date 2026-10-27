# Changelog

## Unreleased

- A workspace's pin in `.github/workflows/docs.yml` now works like a lockfile:
  `asta workspace sync`, run locally, moves a release pin that is behind the
  installed asta forward to its release, without committing, and says so in
  one line. It never moves a pin backward and leaves `main`, `latest` and
  commit pins alone; CI and the Overleaf sync runner build the pin as
  committed. The managed Makefile reruns sync when the installed asta changes,
  and the workspace skill commits a moved pin as its own commit before a PR
  instead of running `asta workspace bump-pin`.

- What changed shows a page title with an HTML entity, such as a non-breaking
  space or `&`, as the page does, instead of the escaped entity text.

- The example workspace's demo is now a pull request's preview, whose What
  changed lists that pull request's edits, and its site has no pages about the
  example; one line on its home page points to its README.

- A paired paper's page now links its Overleaf project, labeled for the
  project's collaborators, when `_quarto.yml` names no link for it under
  `overleaf-links`, so that co-authors reading the site can open the paper to
  edit it.

- Each paper's page is one bar over the paper's PDF, which runs to the
  window's bottom: the paper's name, its source file, whether it's paired with
  Overleaf, an "Open it in Overleaf" link when `_quarto.yml` names one for the
  paper's folder under `overleaf-links`, and in a pull request's preview a
  switch between that pull request's changes marked and the clean paper. ⤢
  hides the site's sidebar and header to give the paper the whole window; Esc
  brings them back. What changed shows a changed paper in the same viewer, a
  page tall, in place of page thumbnails, which previews no longer render.

- Skip temporary clones and all but one GitHub metadata read for an unchanged
  Overleaf sync when the published sync record still matches Overleaf and the
  default branch's paper and pairing, with no sync branch or held lock, and Git
  and GitHub agree on the default branch. Report refused Git probes immediately,
  and reuse local objects from complete checkouts when a workspace clone is
  needed, including linked worktrees. Shallow, grafted, partial and
  alternate-backed checkouts use a regular clone. An unchanged sync seeds a
  missing sync record for later fast runs; a manual no-op publish writes
  nothing. Missing Overleaf authentication fails before the workspace clone,
  with recovery guidance even when no sync record exists.

- Workspace sites use Asta's light and dark palettes (dark by default, with a persistent light toggle),
  consistent typography, and section headings that stay visible while reading.
  Managed sync adopts the theme from compatible selected refs while preserving
  custom themes, CSS, and other output formats.

- Add `asta workspace bump-pin`: when `.github/workflows/docs.yml` pins a
  release older than the installed asta's final release, commit a move of the
  pin to that release as its own commit. The workspace skill runs it before an
  agent opens a PR and drops the commit if the bump breaks the build.
- Add `asta workspace overleaf sync --wait SECONDS` for papers synced by hand:
  one call reruns sync through checks, the quiet merge run and another run's
  recent lock until it completes or a person must act, bounded by the deadline.
  Checks not yet visible keep waiting; the shared deadline prevents starting
  retries or later papers, while an attempt already running finishes normally.
  It ends with one `Sync outcome:` line and exits 0 complete, 4 a person must
  act, 5 still waiting (rerun resumes), 1 an operator must act. Plain `sync`
  for scheduled runners is unchanged. The workspace docs say when to sync by
  hand and when a scheduled runner is worth it.
- Add `asta workspace overleaf check` for an opt-in live round trip on a
  scratch pair reserved for checks: merge co-author edits after GitHub checks,
  publish a workspace edit, then resolve and merge a conflict, moving the pair
  forward. A recent check in progress makes the pair busy; a stale one's
  leftovers are cleared. Release preserves a replacement owner's lock, and the
  timeout (including acquisition) stays below the stale-lock threshold. The
  command waits within one invocation and refuses CI. An explicitly empty
  `sync --check-repo` value refuses sync instead of disabling the release gate.
