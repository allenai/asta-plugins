# Developing

Edit, preview, and save this research project.

## Preview locally

With [Quarto](https://quarto.org) on the host: `make preview`, open `http://localhost:4848`. `make render` builds once to `_site/`; `make clean` wipes artifacts. Automated callers that report a preview link run `make preview-baseline` before pushing and `make preview-ready` after, which blocks until this push's Pages deployment is live. If a transient API or workflow failure interrupts the wait, the baseline remains so the same command can be retried.

With a CLI release containing `asta workspace preview`, that command delegates to your project's `make preview`, including an intentionally empty override, or falls back to Quarto when Make is unavailable or its top-level invocation reports no preview rule. Make diagnostics stay visible before a fallback notice; a nested recipe failure remains an error. The printed URL is available once a server is serving; it is not a health check. Make's successful exit remains success, including empty or up-to-date custom targets; define `.PHONY: preview` for a target that must run even when a `preview` path exists. It ignores inherited `MAKEFLAGS`, `MFLAGS`, `MAKELEVEL`, `GNUMAKEFLAGS` and `MAKEFILES`; other project environment variables still apply, including locale encoding and sorting. Make and its recipes use English diagnostics. Use `make preview` directly when you want those Make controls. Ctrl-C exits with status 130; SIGTERM and SIGHUP exit with 143 and 129. These signals stop the owned foreground preview and its recipe children on POSIX, allowing a short shutdown grace period before forced cleanup. Interrupting a reuse wait leaves the existing preview running.

Repeated CLI starts reuse this project's preview only while its launcher holds `.asta/cache/preview.lock` and port 4848 is listening. A start in progress waits up to sixty seconds, then reports that it is still starting instead of claiming success or launching another server. `.asta/cache/preview.json` records the project path, and the lock file establishes ownership; both use the existing ignored project cache. After acquiring the project lock, a second lock in the user's Asta CLI cache reserves port 4848 across projects before recording ownership or running build prerequisites, and stays held through shutdown. Another project cannot start there until the owner exits; the kernel releases the reservation even if the launcher is killed. The CLI needs writable project and user caches and a foreground preview; use `make preview` directly for a read-only checkout or a target that launches a background server. An unrelated listener at startup remains an error. Reuse checks the launcher lock and listening port, not the identity of the process bound to that port; an external process outside this CLI coordination binding it during startup is not distinguishable.

Managed rules, helpers and the evidence extension use the ref in `.github/workflows/docs.yml`: `@latest` follows final releases, `@main` follows merges, and a release tag or commit pins a version. Change that ref and run `make update-workspace` to refresh the local cache; projects keep control of when to upgrade. A standalone, ejected Makefile can instead set `ASTA_PLUGINS_REF`, defaulting to the newest final release tag. Offline renders keep cached rules and evidence with a warning when a fetch fails; a first fetch needs network access.

## Devcontainer (`.devcontainer/devcontainer.json`)

Based on `ghcr.io/allenai/asta:latest` — Quarto and [Asta](https://asta.allen.ai) pre-installed. Projects with `paper/` use `ghcr.io/allenai/asta:latest-tex`, which adds TeX, LaTeX Workshop, and its build-on-save/PDF-tab settings. Projects do not need to commit `.vscode/settings.json` for these defaults. The image supplies Remote settings, which override User settings; customize them through Workspace settings (`.vscode/settings.json`). The shared recipe keeps outputs in `build/`. Its PDF default loads before user and project `latexmkrc` files, so a paper can choose another engine or DVI/PostScript output.

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
| A separately written LaTeX paper that reuses the project bibliography | Write `paper/main.tex`; its `latexmkrc` locates the shared root `references.bib`. `make paper` builds it (or `make paper PAPER_DIR=<directory>` for another paper). These targets require shared rules from a release containing them; older projects can keep their own targets until upgrading. Every PR preview publishes its PDF, LaTeXML HTML and HTML/PDF diffs. In VS Code, LaTeX Workshop (in the `-tex` image) builds on save with SyncTeX. |

The first path is one-way: Quarto writes LaTeX, nothing converts LaTeX back to `.qmd`. If the paper needs to diverge from the site (venue template, heavy hand edits), switch to the second path and let `paper/main.tex` become the primary copy.

Keeping that intermediate LaTeX is useful even when you only want a PDF: preprint servers such as arXiv ask for the TeX source rather than the PDF of a LaTeX-produced paper, journals and conferences often do too, and the `.tex` is the starting point if the paper later moves to the second path. For LaTeX source, run `quarto render index.qmd --to latex -M cite-method:natbib`. This writes `_site/index.tex` with citation commands and a `\bibliography{references.bib}` line. Plain `--to latex` uses citeproc and writes formatted citations into the source instead. The generated `.tex` still needs the bibliography and a successful PDF build before it is ready to submit.

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

### Managed paper HTML viewers

For each discovered LaTeX paper, the shared preview generates `<paper-dir>/html/index.qmd` before `make check`. This page embeds the LaTeXML rendition in the Quarto site and links the PDF; the paper's HTML and PDF diffs remain in What changed. Keep the LaTeX source and bibliography committed, and ignore only the generated page, for example `/paper/html/index.qmd` in `.gitignore`. Viewer scripts are managed; copy them into `scripts/` only to customize or eject them.

Add the viewer path to `project.render` if your `_quarto.yml` uses an explicit render list, and link it from your navbar or write-up. Automatic render discovery includes it without a list. Managed `make preview`, `make render` and `make check` generate the same missing viewer pages locally through `workspace-viewers`, so explicit render lists work without committed viewer sources. The PDF and LaTeXML artifacts are still built by CI; for local paper compilation and viewing, use LaTeX Workshop. Run `asta workspace sync --refresh --require-scripts` before adopting this behavior; keep custom or existing viewer pages until your installed CLI and selected ref provide the viewer scripts.

Paper artifacts are built after `make check`. The viewer adds PDF/HTML links in the browser only after checking that each artifact exists, leaving ordinary render-time link checks free of premature links. Completed-artifact checks belong in `artifact-command`; they should verify the expected paper files there. Viewing the links and embedded HTML requires JavaScript; missing HTML leaves the PDF available when it built successfully.

Uncommitted generated pages refresh on each build and are removed when their paper disappears only while their content matches the recorded hash. Edited pages and older generated pages without a hash are preserved with a warning. Update explicit render lists and navbar links when moving or removing a paper. To customize or eject a viewer, remove its ignore rule and commit your own `<paper-dir>/html/index.qmd` (or `index.md`/`index.html`). Committed pages, unmarked pages and symlinks are left untouched. Local generation warns and skips when Python is unavailable; set `PYTHON` to select another interpreter. Restart `make preview` after adding or moving a paper so its viewer is generated.

CI generates viewers once using the called workflow revision and committed script overrides. It sets `ASTA_WORKSPACE_VIEWERS=0` for `make check` so locally cached helpers cannot replace those pages.

A committed `scripts/paper-viewer.py` overrides the generator. Overrides are selected per script, so you can customize discovery alone. A custom `scripts/paper-discovery.py` must output a JSON object with a `papers` array of relative directory strings, such as `{"papers": ["paper"]}`; keep that contract compatible with the viewer selected by the project. The generator validates the whole list before creating pages. This supports separately written LaTeX papers; Quarto-to-PDF stays an on-demand render of the `.qmd` source.

CI runs `make check` — the identical command you can run locally before pushing, so a local pass predicts the CI result. New quality gates belong in the `check` target (or a prerequisite target), not in workflow files, so local and CI can't drift.

Projects can set `artifact-command: make preview-artifact-check` under the reusable workflow's `with:` inputs to validate or extend the completed `_site/` (including paper previews and What changed). It runs with read-only permissions before upload and deployment; a failure prevents publication. Leave it unset to keep the usual behavior of publishing the Quarto site even when a paper fails.

The workflow fetches its paper scripts (`paper-discovery.py`, `paper-preview.sh`) from `asta-plugins` at the selected workflow revision, so projects need not commit them. To customize one, commit your copy at `scripts/<name>`; a committed copy always wins. That copy becomes project-owned: upstream fixes no longer reach it automatically, and you must keep its arguments, output schema and exit codes compatible with the selected workflow.

Treat project script overrides as executable code, just like the project's Makefile. They run only in the build job, which grants `contents: read`, has no Pages/OIDC permissions and does not declare or reference secrets. The build is skipped for privileged `pull_request_target` and `workflow_run` events. Deployment uses a separate job with write access and never executes these scripts; call this workflow from `push` or `pull_request` and do not pass secrets to the build.
