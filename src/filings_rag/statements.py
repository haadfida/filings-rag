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
        r"debt[- ]to[- ]equity|book value|cash and cash equivalents",
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

HEAD_LINES = 8
MIN_ROWS = 12


def statements_for(question: str) -> list[str]:
    """Statements a question names or implies, most specific first."""
    return [name for name, cue in CUES.items() if cue.search(question)]


@cache
def statement_pages(doc_name: str) -> dict[str, list[int]]:
    """Zero-indexed pages of each primary statement: the best titled page and, if it continues, the next."""
    pages = parse_document(doc_name)
    found: dict[str, list[int]] = {}
    for name, title in TITLES.items():
        best, best_rows = None, MIN_ROWS - 1
        for p in pages:
            head = " ".join(line.text for line in p.lines[:HEAD_LINES])
            if not title.search(head) or re.search(r"\(continued\)", head, re.IGNORECASE):
                continue
            rows = sum(line.is_row for line in p.lines)
            if rows > best_rows:
                best, best_rows = p.page, rows
        if best is not None:
            chosen = [best]
            nxt = best + 1
            if nxt < len(pages):
                head = " ".join(line.text for line in pages[nxt].lines[:HEAD_LINES])
                other_title = any(t.search(head) for n, t in TITLES.items() if n != name)
                if not other_title and sum(line.is_row for line in pages[nxt].lines) >= MIN_ROWS:
                    chosen.append(nxt)
            found[name] = chosen
    return found
