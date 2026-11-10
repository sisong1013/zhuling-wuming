"""Build .tmp/preview-v5.html from .tmp/preview-v3.html + current CSS/icons/board-foot."""

from __future__ import annotations

import re
from pathlib import Path

GAME = Path(__file__).resolve().parents[1]
STATIC = GAME / "server" / "static"
CSS = (STATIC / "style.css").read_text(encoding="utf-8")
TMP = GAME.parent / ".tmp"

ICONS = {
    "hydro": '<ellipse cx="5.4" cy="10.6" rx="3.5" ry="3.1"/><path d="M8.3 8.2 13.6 2.4" stroke-width="1.5"/><path d="M2.6 11.6h3.2M3.1 9.9h2.7"/>',
    "plum": '<path d="M6.6 8 2.4 5.2v5.6L6.6 8z"/><path d="M9.4 8l4.2-2.8v5.6L9.4 8z"/><circle cx="8" cy="8" r="1.3"/><path d="M7.3 9.3 5.9 14M8.7 9.3l1.4 4.7"/>',
    "brass": '<path d="M8 2.2c1.5 1.5 1.5 4 0 6-1.5-2-1.5-4.5 0-6z"/><path d="M6.4 9.1h3.2v4.5H6.4z"/><path d="M6.4 11.3h3.2"/>',
    "olive": '<path d="M3.7 2.4c7 0 8.9 4.6 8.9 11.2"/><path d="M3.7 2.4v11.2h8.9"/><path d="M5.9 4.3v9.3M8 5.3v8.3M10.1 7.3v6.3"/>',
}
STROKE = 'fill="none" stroke="currentColor" stroke-width="1.15" stroke-linecap="round" stroke-linejoin="round"'


def svg(color: str) -> str:
    return f'<svg viewBox="0 0 16 16" {STROKE}>{ICONS[color]}</svg>'


html = (TMP / "preview-v3.html").read_text(encoding="utf-8")

i = html.index("<style>") + len("<style>")
j = html.index("</style>")
html = html[:i] + "\n" + CSS + "\n" + html[j:]

if "atmosphere__floor" not in html:
    html = html.replace(
        '<div class="atmosphere__grain"></div>',
        '<div class="atmosphere__grain"></div>\n    <div class="atmosphere__floor"></div>',
        1,
    )

for color in ICONS:
    pattern = re.compile(r'(<span class="crest__i" data-c="' + color + r'">)<svg.*?</svg>(</span>)', re.S)
    html = pattern.sub(lambda m, c=color: m.group(1) + svg(c) + m.group(2), html, count=1)

html = re.sub(
    r'(<span class="motif">)<svg.*?</svg>(</span>)',
    lambda m: m.group(1) + svg("hydro") + m.group(2),
    html,
    count=1,
    flags=re.S,
)

if "board-foot" not in html:
    html = html.replace(
        '<p class="hint"></p>',
        '<p class="hint"></p>\n          <div class="board-foot" aria-hidden="true"></div>',
        1,
    )

out = TMP / "preview-v5.html"
out.write_text(html, encoding="utf-8")
print("wrote", out, len(html))
