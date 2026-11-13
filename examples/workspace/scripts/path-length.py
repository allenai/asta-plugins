#!/usr/bin/env python3
"""Draw lit-review/figures/path-length.svg from lit-review/figures/sequence-length.txt.

Run from the project root: python3 scripts/path-length.py
Standard library only. The figure keeps its file name when the sequence length
changes, as a re-run analysis script's output would.

Convention, shared with the review's text: a convolution of kernel 5, stride 1
and no dilation widens what a position sees by 4 per layer (1 + 4L after L
layers), so spanning a sequence of n tokens takes ceil((n - 1) / 4) layers, and
each layer is one step on the path.
"""

import math
from pathlib import Path

figures = Path(__file__).resolve().parents[1] / "lit-review" / "figures"
n = int((figures / "sequence-length.txt").read_text())
rows = [
    ("Recurrent", n),
    ("Convolution, kernel 5", math.ceil((n - 1) / 4)),
    ("Self-attention", 1),
]
W, H, left, top, bar, gap = 640, 230, 190, 52, 34, 18
scale = (W - left - 90) / n
parts = [
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
    'font-family="system-ui, sans-serif">',
    f'<text x="{left}" y="28" font-size="15" fill="#7a8794">Longest path between two tokens, '
    f"{n:,}-token sequence</text>",
]
for i, (name, steps) in enumerate(rows):
    y = top + i * (bar + gap)
    w = max(2, steps * scale)
    parts += [
        f'<text x="{left - 12}" y="{y + bar * 0.68}" font-size="14" fill="#7a8794" '
        f'text-anchor="end">{name}</text>',
        f'<rect x="{left}" y="{y}" width="{w:.1f}" height="{bar}" rx="3" fill="#5b7fa6"/>',
        f'<text x="{left + w + 8:.1f}" y="{y + bar * 0.68}" font-size="14" fill="#7a8794">'
        f"{steps:,}</text>",
    ]
parts.append("</svg>\n")
(figures / "path-length.svg").write_text("\n".join(parts))
