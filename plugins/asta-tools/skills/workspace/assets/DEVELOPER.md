# Developing

Edit, preview, and save this research project.

## Preview locally

With [Quarto](https://quarto.org) on the host: `make preview`, open `http://localhost:4848`. `make render` builds once to `_site/`; `make clean` wipes artifacts. Automated callers that report a preview link run `make preview-baseline` before pushing and `make preview-ready` after, which blocks until this push's Pages deployment is live. If a transient API or workflow failure interrupts the wait, the baseline remains so the same command can be retried.

With Asta CLI 0.107.0 or newer, `asta workspace preview` runs your project's `make preview`, including customized or empty targets. It falls back to Quarto if Make is unavailable or its final diagnostic says the preview rule is missing; other failures remain errors. Output stays in the foreground terminal, and the printed URL is available once the server is serving. The Make invocation uses the C locale for recognizable diagnostics and ignores inherited Make control variables; project settings still apply. Ctrl-C, SIGTERM and SIGHUP stop the owned process group on POSIX and exit 130, 143 and 129. The child runs in a separate session, so shell job control is not supported. Make stderr is streamed through a pipe, which can suppress terminal colors; custom commands must not leave background processes holding that stream open.

Make's exit status is authoritative, not a readiness check: an empty or up-to-date target, including an existing `preview` file or directory without a rule, can exit successfully without serving. Define `.PHONY: preview` alongside the preview recipe so Make always runs it; Quarto fallback only follows a missing-rule diagnostic.

The ignored `.asta/cache/preview.json` records the launcher's PID and project path. On POSIX, a rerun reuses a live recorded launcher when port 4848 responds; if it is still starting, retry after it begins serving. Dead or invalid records, including a record matching the new launcher's own PID, are replaced; an occupied port without a live project record is an error. This lightweight check does not prove listener identity or serialize simultaneous starts: rare competing launches, another process reusing a recorded PID, and an unrelated listener taking the port during startup are accepted limitations. A failed launch reports its underlying error and removes its record. Other platforms report an occupied port rather than probing a recorded PID. Keep custom preview commands in the foreground; use `make preview` directly for background launchers or read-only projects.

Managed rules, helpers and the evidence extension use the ref in `.github/workflows/docs.yml`: `@latest` follows final releases, `@main` follows merges, and a release tag or commit pins a version. Change that ref and run `make update-workspace` to refresh the local cache; projects keep control of when to upgrade. A standalone, ejected Makefile can instead set `ASTA_PLUGINS_REF`, defaulting to the newest final release tag. Offline renders keep cached rules and evidence with a warning when a fetch fails; a first fetch needs network access.

## Devcontainer (`.devcontainer/devcontainer.json`)

Based on `ghcr.io/allenai/asta:latest` — Quarto and [Asta](https://asta.allen.ai) pre-installed. Projects with `paper/` use `ghcr.io/allenai/asta:latest-tex`, which adds TeX Live 2026 (full scheme, pdfLaTeX by default, matching new Overleaf projects), LaTeX Workshop, and its build-on-save/PDF-tab settings. Projects do not need to commit `.vscode/settings.json` for these defaults. The image supplies Remote settings, which override User settings; customize them through Workspace settings (`.vscode/settings.json`). The shared recipe keeps outputs in `build/`. Its PDF default loads before user and project `latexmkrc` files, so a paper can choose another engine or DVI/PostScript output.

- **VS Code locally:** `make dev`, or open folder → Command Palette → **Reopen in Container**. Needs [Docker Desktop](https://www.docker.com/products/docker-desktop/) and the [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers). For an in-editor preview, choose **Ports → Preview in Editor**.
- **Codespaces in a browser:** green **`<> Code`** button → **Codespaces** tab → **Create codespace on main**, or `gh codespace create --web` from the CLI. Port 4848 forwards automatically. Click **Open in Browser** in the notification, use **Ports → Open in Browser**, or click the forwarded URL printed in the `postAttachCommand` terminal. These open the site in a separate browser tab. Do not enter `localhost:4848` in Simple Browser: in a browser-based codespace, `localhost` does not reach the forwarded port. Private forwarded URLs may also fail inside the editor because its embedded frame cannot complete GitHub sign-in. Use the separate tab for the Codespaces preview; local VS Code keeps the in-editor preview above.

Asta auth: run `asta auth login` in the container terminal (device-code flow: open the printed URL in any browser). The VS Code agent and CLI share that login, and in Codespaces it survives container rebuilds. Alternatively set an `ASTA_TOKEN` env var locally or as a Codespaces secret. To get the recommended-secret prompt, create the codespace through **Code → Codespaces → New with options**; CLI creation does not prompt. `ASTA_TOKEN` overrides the login when set, so unset a stale one before logging in.

## Editing `.qmd` files in VS Code

- **First open:** the Quarto extension may ask whether to configure Lua support for the evidence filter in `_extensions/`. Answer it (either choice); citation and YAML completions don't start until you do. Check the notification bell if you missed it.
- **Citations:** in a `.qmd` file, type `@` or `[@` to pick keys from `references.bib`. Completions work in `.qmd` files and `_quarto.yml`, not plain `.md`.
- **Visual editor:** Command Palette → **Quarto: Edit in Visual Mode**, or Ctrl+Shift+F4 (Cmd+Shift+F4 on macOS) to toggle. It adds **Insert → Citation** and WYSIWYG tables. Add `editor: visual` to a page's front matter to open it in visual mode by default.
- **Simple Browser (local VS Code only):** with `make preview` running, Command Palette → **Simple Browser: Show** → `http://localhost:4848`, or **Ports → Preview in Editor**. In a browser-based codespace use the separate tab described above.

## Getting a LaTeX PDF

| You want… | Path |
|-----------|------|
| A PDF of the Quarto write-up itself (to share, print, or submit), with the `.qmd` staying primary | Run `quarto render index.qmd --to pdf` with a TeX toolchain such as the `-tex` image. Quarto builds this PDF through LaTeX, so the same source can also emit the `.tex` source that preprint servers and venues ask for (command below) without maintaining a separate paper. Run it on demand; keeping this rendering path outside the shared `make` targets and PR preview is deliberate. |
| A separately written LaTeX paper that reuses the project bibliography | Write `paper/main.tex`; its `latexmkrc` locates the shared root `references.bib`. `make paper` builds it (or `make paper PAPER_DIR=<directory>` for another paper). These targets require shared rules from a release containing them; older projects can keep their own targets until upgrading. Every PR preview builds inside the `-tex` image and publishes its PDF and, when the LaTeX changed, a latexdiff PDF of the changes. In VS Code, LaTeX Workshop (in the `-tex` image) builds on save with SyncTeX. |

The managed paper preview preserves the `-tex` image's latexmk defaults. On a
host, it skips the system rc unless `LATEXMKRCSYS` explicitly selects one; user
and project `latexmkrc` files still apply. Set `LATEXMKRCSYS=/etc/latexmkrc` if
your host build needs that file. CI script overrides run offline as the runner
UID/GID without a passwd entry; use local files and already-fetched history.

The first path is one-way: Quarto writes LaTeX, nothing converts LaTeX back to `.qmd`. If the paper needs to diverge from the site (venue template, heavy hand edits), switch to the second path and let `paper/main.tex` become the primary copy.

Keeping that intermediate LaTeX is useful even when you only want a PDF: preprint servers such as arXiv ask for the TeX source rather than the PDF of a LaTeX-produced paper, journals and conferences often do too, and the `.tex` is the starting point if the paper later moves to the second path. For LaTeX source, run `quarto render index.qmd --to latex -M cite-method:natbib`. This writes `_site/index.tex` with citation commands and a `\bibliography{references.bib}` line. Plain `--to latex` uses citeproc and writes formatted citations into the source instead. The generated `.tex` still needs the bibliography and a successful PDF build before it is ready to submit.

## Sync a paper with Overleaf

The workspace repo is the reviewed copy; Overleaf is where collaborators edit.

1. On a branch, run `asta workspace overleaf pull https://git.overleaf.com/<project-id>` (later pulls need no URL). It copies the Overleaf project into `paper/`, applies files Overleaf deleted since the last pull, and records the Overleaf commit in `paper/overleaf.json`. Review with `git diff`, commit, and open a PR for the normal paper preview.
2. After the PR merges, run `asta workspace overleaf publish --dry-run`, then `asta workspace overleaf publish`.

Scheduled publishers can pass `--expected-commit <full-id>` to bind publication
to the commit whose checks passed. It requires the exact checkout and fetched
default tip, then rechecks the advertised default branch immediately before
pushing. A changed or unavailable branch refuses with nothing pushed. GitHub
and Overleaf have no shared transaction; a merge after that final check can
still race with the push.

How sync knows where it left off:

- The last sync point is the newer of two records in the workspace repo: the Overleaf commit in `paper/overleaf.json`, which pull writes and you merge through a PR, and the record publish pushes to `origin` at `refs/asta/overleaf/<project-id>`. The record counts only when its workspace commit is on `origin`'s default branch and its Overleaf files match that commit's paper; otherwise pull and publish warn and use `paper/overleaf.json`. Neither Overleaf access nor push access without a reviewed merge can move it.
- Publish exports the committed `paper/` tree (deleting files absent from it) once the paper matches `origin`'s default branch and Overleaf has no edits since the last sync. It then pushes that record, so no sync-record PR is needed. Dry-run pushes nothing and does not run commit hooks, pre-push hooks or signing.
- If Overleaf has edits, publish refuses: pull, review the edits in a PR, then publish. If the record push fails after publishing, the error says so; pull and merge that PR before publishing again.
- Pull reads the record from `origin` and refuses if it can't. A checkout without the published commit merges from `paper/overleaf.json`, so it imports the published edits for review. Without an `origin` remote, pull uses `paper/overleaf.json` alone, and edits published from another clone may need conflict resolution.

See the [sync design notes](https://github.com/allenai/asta-plugins/blob/main/docs/overleaf-sync.md) for the record format and failure handling.

If publication stops at a commit hook or signer, check your workspace's hook and signing configuration. Paper hooks run against the exported paper directory, so a hook requiring workspace-only configuration must use an appropriate configuration path. The later record push skips pre-push hooks. If a remote policy rejects it after the paper was published, pull and merge the sync-record PR before publishing again. Error messages give this guidance without printing raw Git diagnostics, which may contain credentials.

### Authentication

Use your own Overleaf Git token through `OVERLEAF_TOKEN` or a Git credential helper (username `git`, password = token). The same commands work with a service account later. Interactive terminals can prompt for the token; unattended runs require a token or working credential helper and fail instead of waiting for a terminal prompt.

The token is never written to the repo or Git config. With `OVERLEAF_TOKEN`, Git's authentication prompt reads a temporary private token file, deleted after transport. The token value is absent from Git and hook environments, but transport hooks can invoke askpass or read that file. Git configuration, credential helpers and hooks execute as your account and must be trusted, including repository files enabled through `core.hooksPath`. Review that hook code before publishing with personal or service-account credentials. This command does not sandbox hooks. Commit hooks run without the transport's askpass environment.

If the temporary directory forbids executing scripts, use the Git credential helper instead.

### Conflicts and project layout

Publish refuses if Overleaf has changed since the last sync: pull first so those edits get reviewed too. Pull and publish refuse uncommitted changes in `paper/`, except untracked outputs of a local LaTeX build (`.aux`, `.log`, `.bbl`, `.synctex.gz` and similar, plus a `.pdf` with a matching `.tex` filename), so LaTeX Workshop or `latexmk` previews don't block sync. Publish never exports untracked files. Workspace edits to files unchanged in Overleaf are kept. A paper already linked to one Overleaf project cannot be retargeted by passing a different URL; import the other project into a separate directory with `--dir`, relative to the workspace repository root even when `--project` points to a subdirectory.

When both sides edit an existing text source, pull merges against its last synced contents. Non-overlapping lines merge cleanly; overlapping lines get `workspace` / `overleaf` conflict markers to resolve in the PR. Merge output uses the same two-sided style regardless of workspace or global Git conflict-style settings. Pull still writes the merged files and sync record but exits with status 3 (errors exit 1), so scripts can detect conflicts without parsing output. Publish refuses generated conflict-marker labels (`workspace`, `last sync`, `overleaf`) in supported text files, including partially resolved blocks that retain a label. A lone `=======` line is not detected because it can be legitimate source text; remove all separators while resolving conflicts. Differently labeled documentation examples and binary assets do not trigger that check. Literal examples using those exact generated labels must be escaped or relabeled before publication. Automatic line merging is limited to `.tex`, `.ltx`, `.bib`, `.bst`, `.bbx`, `.cbx`, `.sty`, `.cls`, `.clo`, `.def`, `.cfg`, `.dtx`, `.ins`, `.tikz`, `.pgf`, `.csv`, `.tsv`, `.dat`, `.txt` and `.md` files without NUL bytes. Concurrent edits to other assets (including ASCII PDFs, EPS and SVG), files added independently on both sides, and modify/delete disagreements refuse before any copying. Reconcile those files by hand first; one-sided asset changes still sync normally.

Commit all paper assets before publishing, including figures, supplied `.bbl` files and files with build-output suffixes such as `.log` or `.out`. Filename suffixes cannot establish whether a file is source or generated output. Untracked files remain local and are not exported. Once committed, they are exported normally and uncommitted modifications to them block sync.

Sync preserves the project's filenames, bibliography files and LaTeX source layout; it does not require `main.tex` or any particular `.bib` file. Bibliographies use the same line merging and conflict protection as other text sources. Reusing a workspace bibliography is a separate project edit: the agent should stage the chosen file under an agreed name in the paper directory and update the paper's citations/build configuration in a previewed PR. Sync does not combine separate bibliography files or choose a canonical copy. Preview setup is also separate: adapt it to the imported project's actual main document and compiler.

### Sync limitations

Sync requires Git 2.29 or newer; the publish merge check uses `fetch --no-write-fetch-head` to preserve workspace fetch state.

- Both commands refuse unsupported plain-file layouts before copying or pushing: `.gitattributes` (including case and Unicode aliases), Git LFS files, executable files, symlinks (including the selected paper directory), submodules, unsafe paths and names differing only in letter case or Unicode normalization.
- Both commands refuse ignored sync metadata; pull also refuses ignored imports. Adjust the workspace ignore rules so sources can be committed for review. Remote `overleaf.json` is reserved, including names that collide with it by letter case or Unicode normalization. Pull refuses remote `.gitignore` files and publish refuses committed paper `.gitignore` files, including case and Unicode aliases; keep ignore rules in the workspace root so publication cannot make the next pull fail. Publish compares every tracked paper file with its committed contents, even if Git index flags hide local edits or deletions.
- Publish uses the workspace's Git identity, hooks and signing settings, including repo-local settings. Hooks run in the exported paper directory; hooks requiring the full workspace must be adapted for that layout. Relative SSH signing-key and signing-program paths are resolved from the workspace. Shell commands such as `gpg.ssh.defaultKeyCommand` run from the export and must use absolute paths or commands available on `PATH`. A failing hook or signer stops publication. Publish also refuses if hooks or Git conversions change exported bytes, and pushes nothing.
- Case-only renames and reset remote history are unsupported. Pull refuses before copying if Overleaf's current history no longer descends from the recorded commit. Both commands refuse control characters, `.git` filename aliases on HFS+/NTFS, and destinations overlapping Git administrative files before making changes. `--dir <directory>` selects a literal relative directory; use the same spelling and letter case as the committed path. Pull refuses when Overleaf replaces a directory with a file; move the workspace directory aside first. Deletions can leave empty directories.

### Known limits (not handled; avoid these setups)

- Windows: `OVERLEAF_TOKEN` is untested there (use a Git credential helper), and, apart from Git administrative aliases, Windows-reserved names (`CON`, `NUL`, …), trailing dots or spaces and characters such as `:` or `?` are not checked.
- Workspace Git attributes and line-ending conversion (`core.autocrlf`, `text`/`eol`, `filter`, `working-tree-encoding`) on paper files are not checked on pull, so committed bytes can differ from Overleaf's. Publish's final byte check still blocks a changed export.
- Pull is not atomic: a disk or permission error partway through can leave `paper/` partially updated. Inspect `git status`, restore tracked files with `git restore --source=HEAD -- paper`, remove new untracked files, and retry.
- The Overleaf bridge and sync record require SHA-1 commit IDs. Workspace repositories can use SHA-1 or SHA-256; publication messages preserve the full workspace commit ID.
- Transport runs in a temporary Git clone: workspace-local or `includeIf gitdir:` credential helpers, proxy and CA settings are not inherited. Configure those settings globally or for `https://git.overleaf.com` to use your local credentials.
- Filename collision checks cover case folding and NFC/NFD normalization, not every filesystem's naming rules. Normalization-only renames are unsupported. Sync reads source files into memory and is intended for ordinary paper projects, not large asset repositories.
- Git failures report a sanitized command and exit code, with limited authentication/conflict guidance. Detailed stderr is withheld because it can contain credentials. A non-English `LC_ALL` can prevent specific error classification; transport failures still suggest checking credentials, access, network and remote state without changing the locale used by hooks. Invalid sync metadata produces an error naming the record to restore from Git.
- Inspect imported build configuration such as `latexmkrc` before executing it or opening a preview PR. Pushing through Git can drop Overleaf comments and tracked changes in edited regions.

## Back a claim with supporting evidence

A factual claim can carry the source quote that backs it. Add a keyed entry to
`evidence.yml` (verbatim `quote`, a `cite` key from `references.bib`, an optional
`locator` like `p. 4`/`sec. 3.2`/`abstract`), then mark the claim in the `.qmd`:
`[90 tasks]{.ev key="naturebench-count"}`. The claim gets a subtle dotted
underline; hovering it shows the quote and a body-style citation, and the same
popover appears on the `what-changed` diff so a reviewer can check the backing.
Full reference (available after the first render or `make workspace-assets`): [`_extensions/evidence/README.md`](_extensions/evidence/README.md).

## Edit without preview

Edit `.qmd` files on GitHub directly or in any editor.

## Make targets

| target | does |
|---|---|
| `make preview` | live preview on port 4848 |
| `make render` | build to `_site/` |
| `make check` | run the same quality gates CI runs (render + warning validation) |
| `make clean` | wipe Quarto build artifacts |
| `make paper` | compile a separate LaTeX source paper using its latexmkrc |
| `make paper-clean` | clean that paper's build outputs |
| `make workspace-assets` | refresh the evidence extension at the managed ref selected in `docs.yml`; standalone rules default to the newest release tag |
| `make update-workspace` | refresh managed rules and helpers at the selected ref; available with `Makefile.managed` |
| `make dev` | open VS Code attached to devcontainer |
| `make deployed-url` | print deployed URL (needs auto-deploy below) |

Paper builds select `main.tex`, otherwise the single top-level `.tex` file with an uncommented `\documentclass`. If several files declare classes, including `subfiles` or `standalone` children, name the intended root `main.tex` to resolve the ambiguity. The selector recognizes declarations rather than evaluating TeX macros; ambiguous papers warn and skip. A single standalone document remains supported.

The fallback used by `make paper` and `make paper-clean` requires Python 3, included in both workspace images. On a host without Python, use `main.tex` or install Python before invoking those targets for a differently named root. Paper diffs flatten the base source and compile the combined document with the current paper's inputs and Overleaf isolation; they do not rebuild the base PDF independently.

For the optional `Makefile.managed` entry point, set `ASTA_WORKSPACE_LOCAL_GOALS` before the shared scaffold to list project-only targets that need no managed rules or Asta CLI. Mixed commands that also name a shared target still load the rules; a project-owned `workspace.mk` always takes precedence. That file replaces the managed rules completely, so retain the targets your project uses, including `dev` and `clean`.

Managed rules stay cached until the version selected in `docs.yml` changes or you run `make update-workspace`. With a moving channel such as `@latest`, refresh before comparing a local build with CI, which uses the workflow's current revision. Pin a release tag or commit in `docs.yml` if both must stay on a fixed version.

To adopt managed scripts with `Makefile.managed`, first run `asta workspace sync --refresh --require-scripts`. Only after it succeeds, delete the unmodified `scripts/quarto-check.sh` and `scripts/wait-for-preview.sh` copies and run `make check`. The check verifies every script required by the selected rules: older managed refs require the two shell scripts, while refs with `workspace-viewers` also require the discovery and viewer helpers. Check `asta workspace sync --help` for the option; keep project copies until your CLI supports it. Older plugin refs may still require project scripts even with a newer CLI. If an older CLI has not cached the viewer scripts, local generation warns and skips; keep existing viewer pages until the viewer-capable ref passes the preflight.

Keep any customized script in `scripts/`, which always takes precedence. CI warns when a project copy differs from the workflow's version. To eject one script, copy its cached version into `scripts/`. To eject shared rules, copy `workspace.mk` from your selected asta-plugins version into the project root and copy the selected version's `quarto-check.sh`, `wait-for-preview.sh`, `paper-discovery.py` and `paper-viewer.py` into `scripts/` too. Ejected rules alone do not locate the versioned script cache. The standalone full `Makefile` continues to use project scripts without the CLI.

Sync retains old script and archive generations because running builds may still use them. After stopping local builds, delete `.asta/cache/` to reclaim space; the next sync needs network access to fetch it again.

## Auto-deploy (`.github/workflows/docs.yml`)

Every push to `main` and every PR triggers CI checks + deploy. Main: `https://<owner>.github.io/<repo>/`. PRs get a preview URL via bot comment.

`docs.yml` is a thin stub: the build/deploy/preview machinery is a shared [reusable workflow](https://github.com/allenai/asta-plugins/blob/main/.github/workflows/workspace-quarto-site.yml) maintained centrally, so fixes flow to this repo without re-copying (pin its ref to a tag if you prefer explicit upgrades).

The PR's “What changed” page uses the version of `what-changed.py` shipped with the reusable workflow. To customize it, commit `scripts/what-changed.py` in your project; that copy takes precedence and runs in the read-only build job. The write-enabled deploy job only publishes its rendered output. A PR that changes the project script runs its changed copy for its own preview, so treat that page as a review aid rather than a trusted check.

A custom script must accept `--old <site-dir>`, `--new <site-dir>`, `--out <html-file>`, and `--title <text>`. It must write a nonempty HTML file to `--out` and exit successfully to publish the page. `--old` is a snapshot of the deployed main site (empty before the first deploy); `--new` is the PR's rendered `_site/`.

### Local comparisons

Run `asta workspace what-changed <ref>`, for example a tag marking the version you last read. Git 2.30 or newer is required and checked before checkout. The command renders `<ref>` and a private working-tree copy with `make render`, then runs the project's `scripts/what-changed.py` or the copy cached from the asta-plugins ref selected in the working tree's `docs.yml`. Older asta-plugins refs need a project script or a newer selected ref. Use `--project <directory>` for a workspace in a repository subdirectory; both renders use Git's relative project prefix.

The page is written only to `.asta/cache/what-changed/what-changed.html`. This command-owned directory contains a rendered-site copy so links resolve, and is replaced on each successful comparison. Both renders leave the live `_site/` untouched. A failed comparison preserves the previous page.

#### Render inputs and trust

Use a trusted ref: its Makefile and render-time code execute locally, and checkout can run Git hooks or LFS filters. `make render` must finish its build in the foreground; background services must detach their output streams. The baseline contains committed files; submodules are not initialized. Ignored inputs such as data, `_freeze/`, `.env` or `.asta/cache/` are absent unless `make render` prepares them. Missing inputs produce build diagnostics.

The working-tree copy contains repository-wide tracked files with local edits, staged additions/deletions, untracked files that are not ignored, and synced `.asta/cache/` rules. Keeping repository-wide inputs supports Makefiles that reference sibling directories; the command prints the candidate file count before copying. Other ignored files (virtualenvs, data, outputs, logs), untracked `.env` / `.env.*`, and this project's `_site/`, `.quarto/` and previous comparisons stay out. Copying large Git-visible inputs still costs time and temporary disk space.

Both renders run in temporary linked worktrees with independent indexes, so scripts using `git rev-parse --git-common-dir` can find the main checkout's `.venv` without copying it. The copy preserves index file entries, not every index flag: `git add -N` (intent-to-add) paths retain working contents but appear as staged empty blobs. Fully stage or unstage these paths before comparing if your build relies on staging status. Keep source files stable while copying. Symlinked inputs and absolute output paths may remain shared; custom builds must write within their private copy. Live preview can stay open.

The bundled diff script needs only Python's standard library. Custom scripts run with the interpreter running `asta`, which must provide additional dependencies; inline script metadata is not installed automatically. The PR preview continues to use its build environment's `python3`.

#### Preview and cleanup

Run `asta workspace preview --what-changed` to serve the cached site on port 4849, forwarded alongside live preview's port 4848. It prints the localhost or Codespaces URL. Local forwards may use another host port; use the URL shown by your container tools. Later comparisons appear without restarting the server. A request during directory replacement may need a reload.

Publish comparisons sequentially. The cache stays private to the command's user; run its preview as the same user. Host checks accept the configured Codespaces hostname and localhost/IPv4 loopback, including proxies that rewrite Host to localhost. Live Codespaces proxy behavior has not been verified. The server checks request containment and disables directory listings, but accepts the same-user symlink-swap race: a process able to replace private cache files already has your access.

Cleanup removes only the two temporary worktrees, without pruning others. Failed removal preserves the checkout and registration and prints the affected path. Resolve the cause (for a lock, run `git worktree unlock <worktree-path>`), then `git worktree remove --force <worktree-path>` and remove its empty parent directory. If removing an older published cache fails, the command warns but still publishes the new page. After stopping comparisons, remove `.asta/cache/.what-changed-*.previous` to reclaim those copies.

### Managed paper viewers

For each discovered LaTeX paper, the shared preview generates `<paper-dir>/html/index.qmd` before `make check`. This page embeds and links the paper PDF in the Quarto site; the latexdiff PDF of changes remains in What changed. Keep the LaTeX source and bibliography committed, and ignore only the generated page, for example `/paper/html/index.qmd` in `.gitignore`. Viewer scripts are managed; copy them into `scripts/` only to customize or eject them.

Add the viewer path to `project.render` if your `_quarto.yml` uses an explicit render list, and link it from your navbar or write-up. Automatic render discovery includes it without a list. Managed `make preview`, `make render` and `make check` generate the same missing viewer pages locally through `workspace-viewers`, so explicit render lists work without committed viewer sources. The PDFs are still built by CI; for local paper compilation and viewing, use LaTeX Workshop. Run `asta workspace sync --refresh --require-scripts` before adopting this behavior; keep custom or existing viewer pages until your installed CLI and selected ref provide the viewer scripts.

Paper artifacts are built after `make check`. The viewer adds the PDF link and embed in the browser only after checking that the PDF exists, leaving ordinary render-time link checks free of premature links. Completed-artifact checks belong in `artifact-command`; they should verify the expected paper files there. Viewing the link and embedded PDF requires JavaScript.

Uncommitted generated pages refresh on each build and are removed when their paper disappears only while their content matches the recorded hash. Edited pages and older generated pages without a hash are preserved with a warning. Update explicit render lists and navbar links when moving or removing a paper. To customize or eject a viewer, remove its ignore rule and commit your own `<paper-dir>/html/index.qmd` (or `index.md`/`index.html`). Committed pages, unmarked pages and symlinks are left untouched. Local generation warns and skips when Python is unavailable; set `PYTHON` to select another interpreter. Restart `make preview` after adding or moving a paper so its viewer is generated.

CI generates viewers once using the called workflow revision and committed script overrides. It sets `ASTA_WORKSPACE_VIEWERS=0` for `make check` so locally cached helpers cannot replace those pages.

A committed `scripts/paper-viewer.py` overrides the generator. Overrides are selected per script, so you can customize discovery alone. A custom `scripts/paper-discovery.py` must output a JSON object with a `papers` array of relative directory strings, such as `{"papers": ["paper"]}`; keep that contract compatible with the viewer selected by the project. The generator validates the whole list before creating pages. This supports separately written LaTeX papers; Quarto-to-PDF stays an on-demand render of the `.qmd` source.

CI runs `make check` — the identical command you can run locally before pushing, so a local pass predicts the CI result. New quality gates belong in the `check` target (or a prerequisite target), not in workflow files, so local and CI can't drift.

Projects can set `artifact-command: make preview-artifact-check` under the reusable workflow's `with:` inputs to validate or extend the completed `_site/` (including paper previews and What changed). It runs with read-only permissions before upload and deployment; a failure prevents publication. Leave it unset to keep the usual behavior of publishing the Quarto site even when a paper fails.

The workflow fetches its paper scripts (`paper-discovery.py`, `paper-preview.sh`) from `asta-plugins` at the selected workflow revision, so projects need not commit them. To customize one, commit your copy at `scripts/<name>`; a committed copy always wins. That copy becomes project-owned: upstream fixes no longer reach it automatically, and you must keep its arguments, output schema and exit codes compatible with the selected workflow.

Treat project script overrides as executable code, just like the project's Makefile. They run only in the build job, which grants `contents: read`, has no Pages/OIDC permissions and does not declare or reference secrets. The build is skipped for privileged `pull_request_target` and `workflow_run` events. Deployment uses a separate job with write access and never executes these scripts; call this workflow from `push` or `pull_request` and do not pass secrets to the build.

The workspace devcontainer uses `exec asta workspace preview` for attach startup (CLI/image 0.107.0 or newer). Before adopting that hook, select an image containing CLI 0.107.0 or newer. The default `:latest` and `:latest-tex` tags provide it. In Codespaces, run **Codespaces: Rebuild Container** from the Command Palette; locally run **Dev Containers: Rebuild Container**. Rebuilding an older pinned image alone does not upgrade it. Keep the normal skills install command; customize startup by editing `postAttachCommand`, or keep your existing hook when staying on an older image.
