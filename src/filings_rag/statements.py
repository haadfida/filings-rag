"""Find a filing's primary financial statements, and which ones a question needs.

Many FinanceBench questions need numbers from the balance sheet, income statement or cash flow statement.
Search tends to return notes or management's discussion that use the same words instead, so a question
that names or implies a statement is routed to that statement's pages directly.

Statement pages are found by title: a page whose first lines carry a title such as "Consolidated Balance
Sheets" and whose body is mostly table rows. Pages that merely mention a title (a table of contents, an
auditor's report) have few rows and lose to the real statement.
"""

from __future__ import annotations

import re
from functools import cache
from itertools import product

from filings_rag.parse import parse_document

TITLES = {
    "balance_sheet": re.compile(
        r"balance sheets?|statements? of (?:consolidated )?financial (?:position|condition)", re.IGNORECASE
    ),
    "income_statement": re.compile(
        r"statements? of (?:consolidated )?(?:income|operations|earnings|comprehensive income|"
        r"comprehensive \(loss\) income)|income statements?",
        re.IGNORECASE,
    ),
    "cash_flow": re.compile(
        r"statements? of (?:consolidated )?cash flows?|cash flows? statements?", re.IGNORECASE
    ),
}

# Words in a question that point to a statement. Explicit names first, then metrics that live there.
CUES = {
    "balance_sheet": re.compile(
        r"balance sheet|financial position|total assets|current assets|current liabilit|working capital|"
        r"quick ratio|current ratio|inventor|receivable|payable|shareholders'? equity|stockholders'? equity|"
        r"total debt|long-term debt|pp&e|property, plant|return on assets|\broa\b|liquidity|"
        r"debt[- ]to[- ]equity|book value|cash and cash equivalents|\bppn?e\b",
        re.IGNORECASE,
    ),
    "income_statement": re.compile(
        r"income statement|statement of income|statement of operations|p&l|profit and loss|revenue|net sales|"
        r"total sales|gross (?:profit|margin)|operating (?:income|margin|profit)|net income|net earnings|"
        r"\bebit|cost of (?:goods|sales|revenue)|\bcogs\b|eps\b|earnings per share|interest expense|"
        r"return on assets|\broa\b|margin|sg&a|effective tax rate",
        re.IGNORECASE,
    ),
    "cash_flow": re.compile(
        r"cash flow|capital expenditure|capex|purchases? of property|dividends? paid|"
        r"depreciation and amortization|\bd&a\b|free cash flow|cash from operations|operating activities|"
        r"share repurchase|buyback",
        re.IGNORECASE,
    ),
}

# Bump when statement finding or cues change; recorded in run configs.
STATEMENTS_VERSION = "v2"
HEAD_LINES = 8
MIN_ROWS = 12
# Look-alike statements: guarantor and parent-only schedules, segment and supplemental tables.
NOT_PRIMARY = re.compile(
    r"consolidating|guarantor|parent company|registrant|segment|supplemental|selected|summary|"
    r"\(continued\)|pro forma",
    re.IGNORECASE,
)
TITLE_LINE_CHARS = 80
CLUSTER_PAGES = 8


def statements_for(question: str) -> list[str]:
    """Statements a question names or implies, most specific first."""
    return [name for name, cue in CUES.items() if cue.search(question)]


def _rows(page) -> int:
    return sum(line.is_row for line in page.lines)


def _candidates(pages, title: re.Pattern, strict: bool) -> list[tuple[int, int]]:
    """(page, rows) of pages titled as this statement and mostly table rows.

    strict: the title is a short line of its own and the page is not a look-alike (see NOT_PRIMARY).
    """
    out = []
    for p in pages:
        head_lines = [line.text for line in p.lines[:HEAD_LINES]]
        head = " ".join(head_lines)
        if strict:
            titled = any(len(t) <= TITLE_LINE_CHARS and title.search(t) for t in head_lines)
            if not titled or NOT_PRIMARY.search(head):
                continue
            if sum(bool(t.search(head)) for t in TITLES.values()) > 1:  # an index of the statements
                continue
        elif not title.search(head) or re.search(r"\(continued\)", head, re.IGNORECASE):
            continue
        rows = _rows(p)
        if rows >= MIN_ROWS:
            out.append((p.page, rows))
    return out


def _choose(cands: dict[str, list[tuple[int, int]]]) -> dict[str, int]:
    """One page per statement. The primary statements sit together at the start of the financial statements
    section, so pick the earliest combination spanning at most CLUSTER_PAGES pages (later clusters are
    usually a subsidiary's statements filed as an exhibit). Without one, take the tightest combination."""
    names = [n for n in cands if cands[n]]
    if not names:
        return {}
    best, best_key = {}, None
    for combo in product(*(cands[n] for n in names)):
        span = max(p for p, _ in combo) - min(p for p, _ in combo)
        key = (0, min(p for p, _ in combo), span) if span <= CLUSTER_PAGES else (1, span, 0)
        if best_key is None or key < best_key:
            best, best_key = {n: p for n, (p, _) in zip(names, combo, strict=True)}, key
    return best


@cache
def statement_pages(doc_name: str) -> dict[str, list[int]]:
    """Zero-indexed pages of each primary statement: the chosen titled page and, if it continues, the next."""
    pages = parse_document(doc_name)
    cands = {name: _candidates(pages, title, strict=True) for name, title in TITLES.items()}
    for name, title in TITLES.items():  # fall back to the loose rule when no page passes the strict one
        if not cands[name]:
            loose = _candidates(pages, title, strict=False)
            cands[name] = [max(loose, key=lambda c: c[1])] if loose else []
    found: dict[str, list[int]] = {}
    for name, best in _choose(cands).items():
        chosen = [best]
        nxt = best + 1
        if nxt < len(pages):
            head = " ".join(line.text for line in pages[nxt].lines[:HEAD_LINES])
            other_title = any(t.search(head) for n, t in TITLES.items() if n != name)
            if not other_title and _rows(pages[nxt]) >= MIN_ROWS:
                chosen.append(nxt)
        found[name] = chosen
    return found
