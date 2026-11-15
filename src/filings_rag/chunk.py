"""Split parsed pages into retrievable chunks: whole tables, and prose of bounded size.

A table chunk keeps the caption above it, the units the page states, and every row, so a retrieved row is
never separated from its column headers or its units. Very long tables are split with their header rows
repeated. Prose is packed into chunks of about PROSE_CHARS characters at line boundaries. Every chunk
keeps its zero-indexed page, so citations still resolve to pages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from filings_rag.parse import Line, ParsedPage, parse_document

PROSE_CHARS = 1200
TABLE_MAX_LINES = 60
HEADER_LINES = 4  # lines repeated at the top of each part of a split table
CAPTION_LINES = 2


@dataclass(frozen=True)
class Chunk:
    id: str  # "<doc>:<page>:<n>"
    doc_name: str
    page: int  # zero-indexed
    kind: str  # "table" or "prose"
    text: str


def _table_like(line: Line) -> bool:
    return line.is_row or len(line.cells) >= 2


def _short(line: Line) -> bool:
    return len(line.cells) == 1 and len(line.text) <= 100


def _is_year_header(line: Line) -> bool:
    years = [c for c in line.cells if re.fullmatch(r"(?:19|20)\d\d", c.strip())]
    return len(years) >= 2


def _segments(lines: list[Line]) -> list[tuple[str, list[Line]]]:
    """Runs of table lines (allowing short labels such as "Reconciling Items:" inside) and prose lines."""
    segs: list[tuple[str, list[Line]]] = []
    i = 0
    while i < len(lines):
        if _table_like(lines[i]):
            j = i
            while j < len(lines):
                if _table_like(lines[j]):
                    j += 1
                    continue
                # a short single-cell line followed by more table lines stays in the table
                k = j
                while k < len(lines) and k - j < 3 and _short(lines[k]):
                    k += 1
                if k > j and k < len(lines) and _table_like(lines[k]):
                    j = k
                    continue
                break
            segs.append(("table", lines[i:j]))
            i = j
        else:
            j = i
            while j < len(lines) and not _table_like(lines[j]):
                j += 1
            segs.append(("prose", lines[i:j]))
            i = j
    return segs


def chunk_page(doc_name: str, page: ParsedPage) -> list[Chunk]:
    chunks: list[str] = []
    kinds: list[str] = []
    segs = _segments(page.lines)
    last_years: str | None = None  # most recent year-header row on this page
    for idx, (kind, lines) in enumerate(segs):
        if kind == "table":
            own_years = next((ln.text for ln in lines if _is_year_header(ln)), None)
            caption: list[str] = []
            if idx > 0 and segs[idx - 1][0] == "prose":
                caption = [ln.text for ln in segs[idx - 1][1][-CAPTION_LINES:]]
            units = [f"(Amounts in {page.units} unless stated otherwise)"] if page.units else []
            rows = [ln.text for ln in lines]
            if own_years is None and last_years is not None:
                rows = [f"(Columns: {last_years})"] + rows  # keep the column years with every part
            last_years = own_years or last_years
            header = rows[:HEADER_LINES]
            parts = (
                [rows]
                if len(rows) <= TABLE_MAX_LINES
                else [rows[s : s + TABLE_MAX_LINES] for s in range(0, len(rows), TABLE_MAX_LINES)]
            )
            for n, part in enumerate(parts):
                body = part if n == 0 else header + ["..."] + part
                chunks.append("\n".join(caption + units + body))
                kinds.append("table")
        else:
            buf: list[str] = []
            size = 0
            for ln in lines:
                if buf and size + len(ln.text) > PROSE_CHARS:
                    chunks.append("\n".join(buf))
                    kinds.append("prose")
                    buf, size = [], 0
                buf.append(ln.text)
                size += len(ln.text) + 1
            if buf:
                chunks.append("\n".join(buf))
                kinds.append("prose")
    return [
        Chunk(f"{doc_name}:{page.page}:{n}", doc_name, page.page, kind, text)
        for n, (kind, text) in enumerate(zip(kinds, chunks, strict=True))
        if text.strip()
    ]


def chunk_document(doc_name: str) -> list[Chunk]:
    return [c for page in parse_document(doc_name) for c in chunk_page(doc_name, page)]
