<!-- asta-preview/ is canonical (edit here). asta/ is generated — do not edit. -->

# Asta plugins

Two installable plugins, both discoverable via `.claude-plugin/marketplace.json`:

- **`asta-preview/`** — the **canonical source of truth**. Every skill and hook
  lives here; edit them directly. This is the complete (superset) plugin.
- **`asta/`** — **generated**. The core subset: skills whose `SKILL.md`
  frontmatter does *not* set `metadata.internal: true`. Produced from
  `asta-preview/` by `scripts/build-plugins.sh`. **Do not edit by hand.**

Only the small `asta` subset is duplicated; `asta-preview` is never a copy.

Rebuild `asta/` after editing canonical skills or hooks:

```bash
make build-plugins
```

CI fails if `asta/` is out of sync with `asta-preview/`.

## Installing

```bash
# Claude Code + Codex (whole plugins, native plugin system, auto-updates)
npx plugins add allenai/asta-plugins        # interactive: pick asta and/or asta-preview

# Any agent (skills only; core vs. all via frontmatter)
npx skills add allenai/asta-plugins         # core skills
npx skills add allenai/asta-plugins --all   # all skills incl. preview
```
