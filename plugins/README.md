# Asta plugins

Installable plugins, discoverable via `.claude-plugin/marketplace.json`:

- **`asta-tools/`** — research skills (paper search, literature reports, experiments, etc.) and shared permission hooks.
- **`asta-dev/`** — skills for working on Asta itself (`improve-skills`, `research-challenge`). **Requires `asta-tools` to be installed** — its skills depend on the `asta` CLI and the hooks shipped in `asta-tools`.

## Installing

```bash
# Claude Code + Codex (whole plugin, native plugin system, auto-updates)
npx plugins add allenai/asta-plugins                # pick one or both

# Any agent (skills only)
npx skills add allenai/asta-plugins
```
