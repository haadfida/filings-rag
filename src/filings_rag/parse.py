"""Table-aware page parsing: rebuild visual rows from word positions.

PyMuPDF's plain text puts every table cell on its own line, so a row label ends up several lines away
from its numbers ("Depreciation and amortization", "", "1,488", "", "1,544"). Here words are grouped
into visual lines by their vertical position, and wide horizontal gaps become column breaks, so the same
row reads "Depreciation and amortization | 1,488 | 1,544 | 1,474". Each line is tagged as a table row or
prose, and the units stated on the page ("in millions", "in thousands") are recorded.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

import pymupdf

from filings_rag.benchmark import DATA_DIR, pdf_path

PARSER_VERSION = "rows-v2"
CACHE_DIR = DATA_DIR.parent / "cache" / f"parsed-{PARSER_VERSION}"

_NUMBER = re.compile(r"^\(?-?\$?\(?\d[\d,]*(?:\.\d+)?\)?%?\)?$|^[—–-]$")
_YEAR = re.compile(r"^(?:19|20)\d\d$")
_UNITS = re.compile(
    # "(in millions, except per share)", "dollars in thousands", "(Millions)"; a bare "$5 billion" in prose
    # is not a statement of units
    r"\bin (millions|thousands|billions)\b|\((millions|thousands|billions)\b",
    re.IGNORECASE,
)
# Pakistani reports: "Rupees in '000", "(Rupees in thousand)", "Rs. (Millions)", "(Rs. '000s)",
# "(Amounts in thousand)". Tried
# only when the pattern above finds nothing, so FinanceBench pages keep exactly the units they had.
_PKR_UNITS = re.compile(
    r"(?:\brupees|\brs\.?|\bamounts)\s*\(?\s*(?:in\s+)?(?:(thousand|million|billion)s?\b|[\u2018\u2019'`]?\s*000s?\b)",
    re.IGNORECASE,
)
_PKR_ONES = re.compile(r"\.*rupees\.*", re.IGNORECASE)  # a column header of plain "Rupees" (Systems Ltd)


def _units(lines: list[Line]) -> str | None:
    head = " ".join(line.text for line in lines[:15])
    if m := _UNITS.search(head):
        return (m.group(1) or m.group(2)).lower()
    if m := _PKR_UNITS.search(head):
        return f"{m.group(1).lower()}s" if m.group(1) else "thousands"
    if any(sum(bool(_PKR_ONES.fullmatch(c.strip())) for c in line.cells) >= 2 for line in lines[:15]):
        return "rupees"
    return None


@dataclass
class Line:
    text: str  # cells joined with " | "
    cells: list[str]
    y: float
    is_row: bool  # a label followed by numeric cells, or a header of years


@dataclass
class ParsedPage:
    page: int  # zero-indexed
    lines: list[Line]
    units: str | None  # "millions", "thousands", "billions" or None

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


def _is_number(token: str) -> bool:
    return bool(_NUMBER.match(token))


def _visual_lines(words: list[tuple]) -> list[list[tuple]]:
    """Group words whose vertical centres are close into one visual line, top to bottom."""
    if not words:
        return []
    heights = [w[3] - w[1] for w in words if w[3] > w[1]]
    tol = 0.5 * (statistics.median(heights) if heights else 8.0)
    ordered = sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines: list[list[tuple]] = []
    centre = None
    for w in ordered:
        c = (w[1] + w[3]) / 2
        if centre is not None and abs(c - centre) <= tol:
            lines[-1].append(w)
            centre = (centre * (len(lines[-1]) - 1) + c) / len(lines[-1])
        else:
            lines.append([w])
            centre = c
    return [sorted(line, key=lambda w: w[0]) for line in lines]


def _cells(line: list[tuple]) -> list[str]:
    """Split a visual line into cells at gaps wider than about two characters."""
    cells: list[list[str]] = [[line[0][4]]]
    for prev, w in zip(line, line[1:], strict=False):
        char_w = (prev[2] - prev[0]) / max(1, len(prev[4]))
        gap = w[0] - prev[2]
        # a lone "$" belongs to the number after it, so never open a cell after it
        if gap > max(2.2 * char_w, 6.0) and prev[4] != "$":
            cells.append([w[4]])
        else:
            cells[-1].append(w[4])
    out = [" ".join(c).replace("$ ", "$").strip() for c in cells]
    return [c for c in out if c and c != "$"]


def _is_row(cells: list[str]) -> bool:
    tokens = [c for c in cells if c]
    numeric = [c for c in tokens if all(_is_number(t) for t in c.split())]
    if len(numeric) >= 2 and all(_YEAR.match(t) for c in numeric for t in c.split()):
        return True  # header row of years
    return len(tokens) >= 2 and len(numeric) >= 1 and not all(_is_number(t) for t in tokens[0].split())


def parse_page(page: pymupdf.Page) -> ParsedPage:
    words = [w for w in page.get_text("words", sort=False) if w[4].strip()]
    lines: list[Line] = []
    for vl in _visual_lines(words):
        cells = _cells(vl)
        if cells:
            lines.append(Line(" | ".join(cells), cells, round(vl[0][1], 1), _is_row(cells)))
    return ParsedPage(page.number, lines, _units(lines))


def parse_document(doc_name: str, path: Path | None = None) -> list[ParsedPage]:
    """Parsed pages, cached by name. `path` is for PDFs outside FinanceBench (the PSX pilot)."""
    from filings_rag.cachefile import PDF_LOCK, atomic_write_text, lock_for

    cache = CACHE_DIR / f"{doc_name}.json"
    with lock_for(f"parse:{doc_name}"):
        if cache.exists():
            raw = json.loads(cache.read_text(encoding="utf-8"))
            return [ParsedPage(p["page"], [Line(**ln) for ln in p["lines"]], p["units"]) for p in raw]
        with PDF_LOCK, pymupdf.open(path or pdf_path(doc_name)) as pdf:  # PyMuPDF is not thread-safe
            pages = [parse_page(p) for p in pdf]
        atomic_write_text(cache, json.dumps([asdict(p) for p in pages]))
        return pages
