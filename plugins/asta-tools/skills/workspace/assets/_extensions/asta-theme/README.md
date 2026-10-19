# Asta site theme

Gives a workspace site Asta's look — colors, type and components from Asta's
design system ([`asta/DESIGN.md`](https://github.com/allenai/design/blob/main/asta/DESIGN.md)
and [`asta/tokens.json`](https://github.com/allenai/design/blob/main/asta/tokens.json)):

- `dark.scss` — the dark palette: cream text on extra-dark teal, green links.
- `light.scss` — the reversed pair: dark-teal text on cream, teal links. The
  design system's pink `link-reversed` token has only 2.96:1 contrast on cream;
  body links use its teal interactive token (8.00:1) for readable text.
- `asta.css` — shared, mode-independent rules: one font (Manrope; Roboto Mono
  for code), one type scale, and a sticky section heading so a reader of a long
  page can see where they are. Toggling modes changes colors only.
- `fonts/` — Manrope and Roboto Mono as variable WOFF2 files from
  [google/fonts](https://github.com/google/fonts), each beside its SIL Open
  Font License 1.1 text (no Reserved Font Names). Serving them from the site
  means a reader's browser contacts no font host.
- `asta-head.html` — measures the navigation header so pinned headings remain
  visible when it returns on upward scrolling or wraps on a smaller screen.

`make workspace-assets` refreshes this directory from asta-plugins after
`asta workspace sync`, like `_extensions/evidence`. The scaffold `_quarto.yml`
wires it in:

```yaml
format:
  html:
    theme:
      dark: [cosmo, _extensions/asta-theme/dark.scss]
      light: [cosmo, _extensions/asta-theme/light.scss]
    respect-user-color-scheme: false  # start dark; keep a chosen light mode
    css: _extensions/asta-theme/asta.css
    include-in-header:
      - _extensions/asta-theme/asta-head.html
```

Quarto adds the light/dark toggle. To use a different theme, set your own
`theme:` in `_quarto.yml`; to customize this one, commit a copy of
`_extensions/asta-theme` and `make workspace-assets` stops refreshing it.

Sync adopts this theme only when the selected source supplies its assets and
`format.html.theme` is still the scaffold's `cosmo`. Older pins, other formats,
and a local `workspace.mk` stay unchanged. Upgrade the workflow ref to a release
with the theme before adopting it. Offline renders require a complete cached
copy of every extension the configuration references.

Existing project CSS remains after `asta.css`; sync warns with its names when
adopting the theme. Check any hard-coded colors in those files in both modes.
Projects using another theme without references to Asta's assets do not fetch
this extension.
