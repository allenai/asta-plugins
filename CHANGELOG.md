# Changelog

## Unreleased

- What changed shows each slide of a deck from its own small page (about 120 KB for a talk whose whole deck is 6 MB) with the deck's fonts, styles and scripts shared by all slides, so a deck that is new or changes many slides no longer leaves most slide frames blank while each loads the whole deck. Slides still show live, marked in place, with selectable text.
- The workspace's What changed page compares every page of the site, including one with a diagram or a figure computed by code, which it showed only as a link: an equation, figure or diagram (Graphviz, Mermaid) is compared whole and framed Before and After, as are a deck's changed slides, which stack on a narrow screen with each slide whole. An edit reads at two levels, as in GitHub's diff: a wholly added or removed block, table row or source line is shaded light, and inside an edited one only the changed words are marked, darker, the removed struck on red right before the added on green, a changed phrase as one mark. A table is compared row by row, so an inserted row no longer spills into its neighbour, and a changed link shows its old and new target. The page opens with a list of what changed, and unchanged stretches fold into strips that say what they hold. MathJax and Mermaid load only from jsDelivr, pinned with integrity hashes, never from a compared site.
- Use `asta workspace what-changed [ref]` locally and in PR previews, including built-site baselines and lazy, pinned browser provisioning for deck comparisons. Shared Make rules retain only the render contract.
- Preserve evidence popovers and resolve inline citation links in comparison pages.
- `asta workspace what-changed` creates Quarto's Sass cache database before its two concurrent renders start, so a cold start no longer fails with "database is locked".


- A workspace site in a subfolder uses the repository root's `docs.yml` when
  its `site-dir` names the site. Sync and pin moves share that single workflow,
  including paths with spaces. Cached builds validate selection offline without
  moving pins and explain how to upgrade a missing or older CLI. Sync preserves
  concurrent workflow edits and discards conflicting cached rules.
  **Validation compatibility:** all selected workflows, including root-level
  sites, must now be valid single-document YAML with unique relevant mapping
  keys and a literal workspace source on one line. Subfolder roots require
  exactly one workspace job with an explicit `site-dir` input; YAML merge keys
  are not expanded. Root read errors and uncertain selection report errors
  instead of silently using a local workflow. See the workspace developer guide
  for supported YAML forms and CLI installation guidance.

- Workspace `make check` creates temporary files under `${TMPDIR:-/tmp}` so it
  works in agent sandboxes.

- `asta autodiscovery` names the caller as `me` in API paths instead of reading
  the user id out of the access token, so it works with any token the service
  accepts, not only a JWT whose subject is the user id.

- `asta auth login` warns after it succeeds if `ASTA_TOKEN` is set: commands
  use that variable instead of the stored login. Unset it, or run
  `env -u ASTA_TOKEN asta …`, to use the login.

- The shared workspace site workflow supports a subfolder and render-path
  filtering. Keep `contents: write`, `pull-requests: write` and `pages: read`
  in existing `docs.yml` callers when upgrading (as in the shipped template):
  scope reads PR files and cleanup removes obsolete bot preview comments.
  Unrelated PRs skip building; reverted site changes and closed PRs remove their
  previews and preview comments. `render-paths` uses Python fnmatch, where both
  `*` and `**` cross directory separators. One site per repository owns the
  `gh-pages` root.

- Slide decks keep a consistent slide background in the phone scroll view,
  while preserving each slide's custom background. The workspace example labels
  its deck as slides in the sidebar and overview.

- Workspaces now support multiple Markdown slide decks in nested `slides.qmd`
  folders. The `asta-slides` Quarto reveal.js extension uses the Asta theme and
  bundled fonts, 16:9 slides, controls and slide numbers inside the scaled slide,
  section labels, optional dimming builds, and standalone math. Decks build and
  link with the site; PR previews show slide-level diffs. The workspace example
  includes a talk, with offline and projector geometry checks in CI.

- A paper turns on scheduled Overleaf sync with `"schedule": true` in its
  pairing record. `asta workspace overleaf pull` sets it when it first pairs a
  paper (`--no-schedule` keeps the paper manual); a later `pull --schedule` or
  `--no-schedule`, or a PR, changes it.
  `asta workspace overleaf sync --github-owner <user or org>` finds the
  scheduled papers in that owner's repositories with one GitHub code search,
  clones each, syncs it, and carries on past a failing one. The
  `ghcr.io/allenai/asta` image now ships `gh`.

- The autodiscovery skill's local workflow now covers running on an Anthropic
  key (Claude Opus 5) and recommends GPT-6 Luna on an OpenAI key. It names the
  installed CLI `auto-discovery` throughout, fixes the model names and Vertex
  variables, and lists known behaviours: runs that never stop when every call
  fails, and safety-filter stops that end a run with no experiments. Local
  runs now start through `scripts/run_relaxed.py`, which runs it with a
  reviewer that fails an experiment only when its main result is wrong or
  untested.

- Theorizer and AutoDiscovery install on a pinned Python in the run-workflow
  skill and the autodiscovery skill. On the newest Python a dependency they
  share has no prebuilt package and the install fails while compiling it.
  Theorizer also pins `pymupdf4llm` below 2.0, whose PyPI release is an empty
  package that leaves imported PDFs without text.

- The theory generation workflow lets Theorizer choose its models from the key
  it finds, rather than naming OpenAI's, so a run on an Anthropic key uses
  Claude. It says what to do when a model's safety filter stops a generation:
  Theorizer reports it only as a `TypeError`, and generating again on
  `claude-opus-5` has passed where `claude-opus-5-5` did not, without
  extracting anything again.

- The generate-theories skill points to the run-workflow skill's theory
  generation workflow for people running on their own key rather than on Asta
  credits.

- When the workspace skill creates a workspace's GitHub repo, or sets up one
  that exists but is empty, it proposes a private repo, a private Pages site
  with a preview and What changed for every PR, and both default-branch
  rulesets, and deleting branches after merge in one message, each with what
  leaving it out costs, and applies them on one yes. It checks that the site
  is private, and stops to ask the owner if it can't be or if they want the
  repo public. Overleaf pairing then checks these instead of asking
  again, and asks only for the sync account's Editor invite and link sharing
  off in Overleaf.

- A workspace's pin in `.github/workflows/docs.yml` now works like a lockfile:
  `asta workspace sync`, run locally, moves a release pin that is behind the
  installed asta forward to its release, without committing, and says so in
  one line. It never moves a pin backward and leaves `main`, `latest` and
  commit pins alone; CI and the Overleaf sync runner build the pin as
  committed. The managed Makefile reruns sync when the installed asta changes,
  and the workspace skill commits a moved pin as its own commit before a PR
  instead of running `asta workspace bump-pin`. If the new release cannot be
  fetched, sync keeps the old pin and tries its rules, including an offline
  cached copy. Concurrent workflow edits are preserved, and agents commit a
  pin move only after its checks pass.

- Workspace papers compile past LaTeX errors like Overleaf: a produced PDF
  passes with error and citation-warning counts and a log on the paper page
  and PR comment. Failed default-branch builds retain the last published PDF
  and matching bibliography; the live example remains strict. Rebuilds clear
  stale bibliography artifacts and publish the arXiv bibliography download
  only after a successful compilation without citation or bibliography warnings.

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
  pin to that release as its own commit. This explicit command remains available;
  workspace agents now use sync as described above.
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
