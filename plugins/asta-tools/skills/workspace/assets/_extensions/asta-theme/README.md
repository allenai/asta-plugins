# Asta site theme

Gives a workspace site Asta's look — colors, type and components from Asta's
design system ([`asta/DESIGN.md`](https://github.com/allenai/design/blob/main/asta/DESIGN.md)
and [`asta/tokens.json`](https://github.com/allenai/design/blob/main/asta/tokens.json)):

- `dark.scss` — the dark palette (the default): cream text on extra-dark teal,
  green links.
- `light.scss` — the reversed pair: dark-teal text on cream, teal links. The
  design system's pink `link-reversed` token has only 2.96:1 contrast on cream;
  body links use its teal interactive token (8.00:1) for readable text.
- `asta.css` — shared, mode-independent rules: one font (Manrope; Roboto Mono
  for code), one type scale, a sticky section heading so a reader of a long
  page can see where they are, and the theme switch: a "Light | Dark" control
  under the site title, as tall as the search box. Toggling modes changes colors
  only. It also gives Mermaid edge labels the theme's label colors, which
  Mermaid's own grey label boxes otherwise cover. Both SCSS files set
  `$mermaid-edge-color` to the text color, so that edge lines and arrowheads
  reach 12:1 or more in each mode (Quarto's default is 1.8:1 in dark and 1.4:1
  in light).
- `fonts/` — Manrope and Roboto Mono as variable WOFF2 files from
  [google/fonts](https://github.com/google/fonts), each beside its SIL Open
  Font License 1.1 text (no Reserved Font Names). Serving them from the site
  means a reader's browser contacts no font host.
- `asta-head.html` — measures the navigation header so pinned headings remain
  visible when it returns on upward scrolling or wraps on a smaller screen,
  gives Quarto's scripts an in-memory stand-in for browser storage when the page
  is shown in a sandboxed frame where touching it throws, and keeps the reader's
  theme there: in a sandboxed frame storage lasts one page, so the embedding app
  keeps the choice. The embedder hands it in as `<html data-wsfd-theme="light|dark">`
  or as the frame's name (`wsfd:theme=light`) before Quarto picks its stylesheets,
  and a switch is announced with a `wsfd:theme` window event (`detail.theme`) and
  written back to the frame's name. On an ordinary site Quarto's own localStorage
  keeps it.

`make workspace-assets` refreshes this directory from asta-plugins after
`asta workspace sync`, like `_extensions/evidence`. The scaffold `_quarto.yml`
wires it in:

```yaml
format:
  html:
    theme:
      dark: [cosmo, _extensions/asta-theme/dark.scss]   # listed first: the default
      light: [cosmo, _extensions/asta-theme/light.scss]
    respect-user-color-scheme: false  # start dark; keep a chosen light mode
    css: _extensions/asta-theme/asta.css
    include-in-header:
      - _extensions/asta-theme/asta-head.html
```

Quarto adds the light/dark toggle; `asta.css` restyles it. To use a different theme, set your own
`theme:` in `_quarto.yml`; to customize this one, commit a copy of
`_extensions/asta-theme` and `make workspace-assets` stops refreshing it.

Sync adopts this theme only when the project's Makefile includes the managed
`.asta/cache/workspace.mk` rules, the selected source supplies its assets, and
`format.html.theme` is still the scaffold's `cosmo`. Older pins, other formats,
and a local `workspace.mk` stay unchanged. Upgrade the workflow ref to a release
with the theme before adopting it. Offline renders require a complete cached
copy of every extension the configuration references.
Committed or symlinked theme copies keep their project-defined file set, including
offline; the bundled-font completeness checks apply only to managed copies.

Existing project CSS remains after `asta.css`; sync warns with its names when
adopting the theme. Check any hard-coded colors in those files in both modes.
Projects using another theme without references to Asta's assets do not fetch
this extension.
Asset detection scans root `_quarto*.yml` files. If the only reference is in
page front matter, `_metadata.yml`, or other included YAML, also add the theme
stylesheet to the root HTML configuration to enable fetching it.
