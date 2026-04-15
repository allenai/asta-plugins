---
name: Workspace
description: Set up a GitHub Codespaces or Dev Container environment with Asta skills installed in GitHub Copilot and Quarto pre-configured. Use when asked to set up a Codespace or devcontainer for an Asta project.
---

# Workspace

Set up a VS Code environment (GitHub Codespaces or Dev Containers) with Asta skills installed in the GitHub Copilot agent. Includes Quarto pre-installed with preview auto-starting on port 4848.

## Setup

If the project doesn't have `.devcontainer/devcontainer.json` yet, confirm the plan with the user, then:

1. Copy [assets/devcontainer.json](assets/devcontainer.json) to `.devcontainer/devcontainer.json`.
2. Open the environment — via Codespaces or VS Code ("Reopen in Container"). If the project has a `_quarto.yml`, preview starts automatically on port 4848 — click "Open in Browser" in the notification to view it. Users with the `quarto.quarto` VS Code extension get additional editor support.
3. Authenticate with Asta in a terminal inside the container: run `asta auth login`, or set `ASTA_TOKEN` in the environment before starting the container and it will be passed through automatically.
