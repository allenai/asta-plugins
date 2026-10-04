# Developing

Edit, preview, and save this research project.

## Preview locally

With [Quarto](https://quarto.org) on the host: `make preview`, open `http://localhost:4848`. `make render` builds once to `_site/`; `make clean` wipes artifacts. Automated callers that report a preview link run `make preview-baseline` before pushing and `make preview-ready` after, which blocks until this push's Pages deployment is live. If a transient API or workflow failure interrupts the wait, the baseline remains so the same command can be retried. The `uses: ...@<ref>` line in `docs.yml` controls the workflow, `what-changed.py`, drift checks and evidence extension fetched by the render targets. The default `@latest` follows final releases without a project PR; it is a mutable ref, so a bad release or a compromised release branch can affect downstream CI. Use `@vX.Y.Z` when upgrades need review in this project, or `@main` to track unreleased changes (`ASTA_PLUGINS_REF` overrides it for the render targets only). The devcontainer image has its own tag in `devcontainer.json`; choose the matching release or channel there. During promotion, the workflow ref and `:latest` image may change a short time apart. Offline is tolerated: if the fetch can't reach `asta-plugins` but a previously fetched `_extensions/evidence/` is present, the render keeps that cached copy and warns instead of failing; only a first fetch with no cache is a hard error.

## Devcontainer (`.devcontainer/devcontainer.json`)

Based on `ghcr.io/allenai/asta:latest` — Quarto and [Asta](https://asta.allen.ai) pre-installed. Projects with `paper/` use `ghcr.io/allenai/asta:latest-tex`, which adds TeX and the LaTeX Workshop extension for local PDF builds.

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
| A PDF of the Quarto write-up itself (to share, print, or submit), with the `.qmd` staying primary | Run `quarto render index.qmd --to pdf` with a TeX toolchain such as the `-tex` image. Quarto builds this PDF through LaTeX, so the same source can also emit the `.tex` source that preprint servers and venues ask for (command below) without maintaining a separate paper. This path is not yet a `make` target or part of the PR preview. |
| A separately written LaTeX paper that reuses the project bibliography | Write `paper/main.tex` citing `../references.bib`. `make paper` builds it, and every PR preview publishes its PDF and a LaTeX diff. In VS Code, LaTeX Workshop (in the `-tex` image) builds on save with SyncTeX. |

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
| `make clean` | wipe build artifacts |
| `make workspace-assets` | refresh the evidence extension from `asta-plugins` (latest version tag by default) |
| `make dev` | open VS Code attached to devcontainer |
| `make deployed-url` | print deployed URL (needs auto-deploy below) |

## Auto-deploy (`.github/workflows/docs.yml`)

Every push to `main` and every PR triggers CI checks + deploy. Main: `https://<owner>.github.io/<repo>/`. PRs get a preview URL via bot comment.

`docs.yml` is a thin stub: the build/deploy/preview machinery is a shared [reusable workflow](https://github.com/allenai/asta-plugins/blob/main/.github/workflows/workspace-quarto-site.yml) maintained centrally, so fixes flow to this repo without re-copying (pin its ref to a tag if you prefer explicit upgrades).

CI runs `make check` — the identical command you can run locally before pushing, so a local pass predicts the CI result. New quality gates belong in the `check` target (or a prerequisite target), not in workflow files, so local and CI can't drift.
