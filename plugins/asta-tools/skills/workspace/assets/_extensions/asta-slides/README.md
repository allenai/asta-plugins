# Asta slides

A Quarto custom reveal.js format for workspace talks. Each deck lives in its
own folder, with `slides.qmd`, images, SCSS and scripts beside one another.
`make render` builds every deck with the website; each becomes
`<deck-dir>/slides.html`. The file embeds its resources, including math and
fonts, so it can be shared independently of the site. Math uses Quarto's KaTeX
renderer by default: Quarto 1.7's reveal.js MathJax loader still requests a remote
library despite `self-contained-math`
([upstream issue](https://github.com/quarto-dev/quarto-cli/issues/9404)). A deck can override `html-math-method`
using ordinary Quarto options; recheck offline behavior after changing it. External video, remote
iframes and resources deliberately loaded by a custom script still require
network access.

```yaml
---
title: A research talk
format: asta-slides-revealjs
---
```

Use `#` headings for sections and `##` headings for individual slides. By
default a headline across the top of each slide lists every section and
highlights the current one, as Beamer's section headlines do, so the audience
sees where they are and what is ahead. Set `section-header: current` to show
only the current section's name. The headline lines up with the slide titles,
is hidden on the title slide (and, with `current`, before the first section),
and is absent from a deck with no sections. Arrows follow Quarto's default
`controls: auto`: shown only when the deck is embedded or has vertical slides;
when shown, the slide number sits to their left. The headline, native controls
and native slide number are children of Reveal's scaled slide container, with
dimensions in slide units. The default slide is 1600 × 900 (16:9). Quarto's window-edge menu and
progress bar are off by default; ordinary `menu` and `progress` options can
re-enable them.

For incremental builds that dim previous fragments, add `.dim-previous` to a
slide or fragment container. Use Reveal's usual `.fragment` or Quarto's
`incremental` syntax to choose the build steps. Unmarked slides retain normal
Reveal behavior.

## Customize a deck

Layer a deck-local SCSS file after the theme:

```yaml
format:
  asta-slides-revealjs:
    theme: [default, ../../_extensions/asta-slides/asta-slides.scss, talk.scss]
    include-after-body: talk.html
    revealjs-plugins:
      - name: MyPlugin
        path: .
        script:
          - path: plugin.js
```

The extension path is relative to this example's two-level deck folder; adjust
it to match yours. Quarto's ordinary `include-in-header`, `include-after-body`
and `revealjs-plugins` options remain available. See the
[Quarto plugin guide](https://quarto.org/docs/presentations/revealjs/advanced.html#reveal-plugins)
for plugin bundles. In `talk.scss`, override variables in the defaults section:

```scss
/*-- scss:defaults --*/
$asta-bg: #faf2e9;
$asta-fg: #0a3235;
$asta-link: #105257;
$asta-font: Manrope, Arial, sans-serif;
$asta-heading-font: $asta-font;
$asta-mono-font: "Roboto Mono", monospace;
```

Replace the Asta theme with Quarto's native `theme` option, for example
`format: {asta-slides-revealjs: {theme: default}}`. This also resets the code,
table, callout and title styling. The remaining additions can be disabled
independently in document metadata:

```yaml
asta-slides:
  section-header: false
  slide-number: false
  controls: false
  dim-previous: false
```

`section-header` takes `all` (the default), `current` or `false`; turning it
off also removes the top padding it reserves, so titles move up. The other three
default to `true`; dimming still requires the optional class. Native
Quarto options such as `controls`, `slide-number: false`, `width`,
`height`, `embed-resources` and `self-contained-math` also remain customizable.
Do not use window units (`vw`, `vh`) for additions intended to fit the slide.

`make workspace-assets` fetches the extension at the same selected source ref
as the site's other managed assets. To eject it, commit the whole
`_extensions/asta-slides/` directory (remove its ignore entry first). A committed
copy or a local development symlink is preserved on refresh. Fonts ship under
SIL OFL 1.1; their license files are in `fonts/`.

## Share the single HTML page

Use the rendered `slides.html`, not the Markdown source, when sharing a
standalone page. An agent with access to claude.ai can create an HTML artifact
from that file and check that navigation, fonts, math and section labels work
there. A browser's offline check does not establish compatibility with the
claude.ai artifact sandbox; check that surface explicitly before claiming it.
