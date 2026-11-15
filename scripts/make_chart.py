"""Draw the README's headline chart from the saved results: test-split correct and grounded accuracy.

Writes docs/results-light.svg and docs/results-dark.svg (the README picks one by colour scheme).
Run from the repository root: python scripts/make_chart.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

ROWS = [  # label, note, results file
    ("Model's memory only", "no documents", "milestone-4/closed_book-judge-v2.json"),
    ("Keyword search", "BM25, top 5 pages", "milestone-4/bm25-judge-v2.json"),
    ("Statement routing", "milestone 4", "milestone-4/routed.json"),
    ("filings-rag", "routing + query rewrites", "milestone-5/routed_rewrite.json"),
    ("Evidence pages given", "ceiling", "milestone-5/oracle-judge-v2.json"),
]
HIGHLIGHT = "filings-rag"

THEMES = {
    "light": {
        "surface": "#fcfcfb",
        "text": "#0b0b0b",
        "text2": "#52514e",
        "muted": "#8a8984",
        "grid": "#e6e5e1",
        "s1": "#2a78d6",
        "s2": "#eb6834",
    },
    "dark": {
        "surface": "#1a1a19",
        "text": "#f0efec",
        "text2": "#c3c2b7",
        "muted": "#8f8e86",
        "grid": "#33332f",
        "s1": "#3987e5",
        "s2": "#d95926",
    },
}

W = 760
LEFT = 210  # label column
RIGHT = 60
PLOT = W - LEFT - RIGHT
BAR = 14
PAIR_GAP = 2
ROW_H = 54
TOP = 92


def scores(path: str) -> tuple[float, float]:
    s = json.loads((RESULTS / path).read_text(encoding="utf-8"))["test"]["scores"]
    return s["correct"], s["grounded"]


def bar(x: float, y: float, w: float, h: float, fill: str) -> str:
    """A bar anchored at x with a 4px rounded data end."""
    if w <= 0:
        return ""
    r = min(4.0, w, h / 2)
    return (
        f'<path d="M{x:.1f},{y:.1f} h{w - r:.1f} a{r},{r} 0 0 1 {r},{r} v{h - 2 * r:.1f} '
        f'a{r},{r} 0 0 1 {-r},{r} h{-(w - r):.1f} z" fill="{fill}"/>'
    )


def svg(theme: dict) -> str:
    data = [(label, note, *scores(path)) for label, note, path in ROWS]
    h = TOP + ROW_H * len(data) + 40
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}" '
        f'font-family="-apple-system, Segoe UI, Helvetica, Arial, sans-serif" role="img" '
        f'aria-label="Test-set accuracy: correct and grounded, by method">',
        f'<rect width="{W}" height="{h}" rx="8" fill="{theme["surface"]}"/>',
        f'<text x="24" y="34" font-size="17" font-weight="600" fill="{theme["text"]}">'
        f"FinanceBench, 100 held-out questions</text>",
        f'<text x="24" y="56" font-size="13" fill="{theme["text2"]}">'
        f"Grounded = correct and cites a page the benchmark marks as evidence</text>",
    ]
    # Legend
    lx = LEFT
    for key, name in (("s1", "Correct"), ("s2", "Grounded")):
        out.append(f'<rect x="{lx}" y="69" width="10" height="10" rx="2" fill="{theme[key]}"/>')
        out.append(f'<text x="{lx + 16}" y="78" font-size="12" fill="{theme["text2"]}">{name}</text>')
        lx += 96
    # Grid
    grid_bottom = TOP + ROW_H * len(data) - 8
    for pct in (0, 25, 50, 75, 100):
        x = LEFT + PLOT * pct / 100
        out.append(
            f'<line x1="{x:.1f}" y1="{TOP - 6}" x2="{x:.1f}" y2="{grid_bottom}" '
            f'stroke="{theme["grid"]}" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{x:.1f}" y="{grid_bottom + 18}" font-size="11" text-anchor="middle" '
            f'fill="{theme["muted"]}">{pct}%</text>'
        )
    # Rows
    for i, (label, note, correct, grounded) in enumerate(data):
        y = TOP + ROW_H * i
        weight = "700" if label == HIGHLIGHT else "500"
        out.append(
            f'<text x="24" y="{y + 15}" font-size="14" font-weight="{weight}" fill="{theme["text"]}">'
            f"{label}</text>"
        )
        out.append(f'<text x="24" y="{y + 32}" font-size="12" fill="{theme["muted"]}">{note}</text>')
        for j, (value, key) in enumerate(((correct, "s1"), (grounded, "s2"))):
            by = y + j * (BAR + PAIR_GAP)
            w = PLOT * value
            out.append(bar(LEFT, by, w, BAR, theme[key]))
            out.append(
                f'<text x="{LEFT + w + 6:.1f}" y="{by + BAR - 3}" font-size="12" font-weight="{weight}" '
                f'fill="{theme["text"]}">{value * 100:.0f}%</text>'
            )
    out.append("</svg>")
    return "\n".join(o for o in out if o) + "\n"


def main() -> None:
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    for name, theme in THEMES.items():
        (docs / f"results-{name}.svg").write_text(svg(theme), encoding="utf-8")
        print(f"wrote docs/results-{name}.svg")


if __name__ == "__main__":
    main()
