# Asta site theme

Gives a workspace site Asta's look — colors, type and components from Asta's
design system (`allenai/design`, `asta/DESIGN.md` + `asta/tokens.json`):

- `dark.scss` — the dark palette: cream text on extra-dark teal, green links.
- `light.scss` — the reversed pair: dark-teal text on cream, pink links.
- `asta.css` — shared, mode-independent rules: one font (Manrope; Roboto Mono
  for code), one type scale, and a sticky section heading so a reader of a long
  page can see where they are. Toggling modes changes colors only.

`make workspace-assets` refreshes this directory from asta-plugins after
`asta workspace sync`, like `_extensions/evidence`. The scaffold `_quarto.yml`
wires it in:

```yaml
format:
  html:
    theme:
      light: [cosmo, _extensions/asta-theme/light.scss]
      dark: [cosmo, _extensions/asta-theme/dark.scss]
    respect-user-color-scheme: true   # follow the reader's system setting
    css: _extensions/asta-theme/asta.css
```

Quarto adds the light/dark toggle. To use a different theme, set your own
`theme:` in `_quarto.yml`; to customize this one, commit a copy of
`_extensions/asta-theme` and `make workspace-assets` stops refreshing it.
