# Asta plugins

Installable plugins, discoverable via `.claude-plugin/marketplace.json`:

- **`asta-tools/`** — research skills (paper search, literature reports, experiments, etc.) and shared permission hooks. Install this one to use Asta.
- **`asta-flows/`** — autonomous research flows built on top of Asta (`asta-flows`). **Requires `asta-tools`.**
- **`asta-dev/`** — skills for working on Asta itself (`improve-skills`, `research-challenge`). **Requires `asta-tools`.**

## Installing

```bash
# Claude Code + Codex (whole plugin, native plugin system, auto-updates)
npx plugins add allenai/asta-plugins                # pick the plugins you want

# Any agent (skills only)
npx skills add allenai/asta-plugins
```
