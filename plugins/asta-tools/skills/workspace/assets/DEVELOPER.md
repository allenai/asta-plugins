# Developing

Edit, preview, and save this research project.

## Preview locally

With [Quarto](https://quarto.org) on the host: `make preview`, open `http://localhost:4848`. `make render` builds once to `_site/`; `make clean` wipes artifacts.

## Devcontainer (`.devcontainer/devcontainer.json`)

Based on `ghcr.io/allenai/asta:latest` — Quarto and [Asta](https://asta.allen.ai) pre-installed.

- **VS Code locally:** `make dev`, or open folder → Command Palette → **Reopen in Container**. Needs [Docker Desktop](https://www.docker.com/products/docker-desktop/) and the [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers).
- **Codespaces:** green **`<> Code`** button → **Codespaces** tab → **Create codespace on main**, or `gh codespace create --web` from the CLI. Port 4848 auto-forwards.

Asta auth: set `ASTA_TOKEN` env var locally before launching, or `asta auth login` in the container. For Codespaces: add `ASTA_TOKEN` as a secret.

## Edit without preview

Edit `.qmd` files on GitHub directly or in any editor.

## Make targets

| target | does |
|---|---|
| `make preview` | live preview on port 4848 |
| `make render` | build to `_site/` |
| `make check` | run the same quality gates CI runs (render + warning validation) |
| `make clean` | wipe build artifacts |
| `make dev` | open VS Code attached to devcontainer |
| `make deployed-url` | print deployed URL (needs auto-deploy below) |

## Auto-deploy (`.github/workflows/docs.yml`)

Every push to `main` and every PR triggers CI checks + deploy. Main: `https://<owner>.github.io/<repo>/`. PRs get a preview URL via bot comment.

`docs.yml` is a thin stub: the build/deploy/preview machinery is a shared [reusable workflow](https://github.com/allenai/asta-plugins/blob/main/.github/workflows/workspace-quarto-site.yml) maintained centrally, so fixes flow to this repo without re-copying (pin its ref to a tag if you prefer explicit upgrades).

CI runs `make check` — the identical command you can run locally before pushing, so a local pass predicts the CI result. New quality gates belong in the `check` target (or a prerequisite target), not in workflow files, so local and CI can't drift.
