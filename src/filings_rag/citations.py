"""Page citations in answers, and grounded accuracy.

Answers cite pages as "[p. 49]", "[p. 49, p. 50]", "[pp. 49-51]" or "[p. 4, 5, 6]" (one-indexed, as a
reader sees them). An answer is *grounded* when it is graded correct and at least one cited page is a
page the benchmark marks as evidence. Closed-book answers cite nothing, so they are never grounded:
this is what separates retrieval from what the model remembers.
"""

from __future__ import annotations

import re

from filings_rag.benchmark import Question

_BRACKET = re.compile(r"\[([^\[\]]{1,200})\]")
_PAGES = re.compile(r"\bpp?\.\s*((?:\d+\s*(?:[-–]\s*\d+)?\s*(?:,|;|and)?\s*)+)", re.IGNORECASE)
_ITEM = re.compile(r"(\d+)(?:\s*[-–]\s*(\d+))?")
MAX_RANGE = 20  # a "range" longer than this is more likely a typo than a citation


def cited_pages(answer: str | None) -> set[int]:
    """One-indexed page numbers cited in square brackets."""
    pages: set[int] = set()
    for group in _BRACKET.findall(answer or ""):
        for run in _PAGES.findall(group):
            for start, end in _ITEM.findall(run):
                a = int(start)
                b = int(end) if end else a
                if a <= b <= a + MAX_RANGE:
                    pages.update(range(a, b + 1))
                else:
                    pages.add(a)
    return pages


def cites_evidence(q: Question, answer: str | None) -> bool:
    """True when the answer cites at least one page the benchmark marks as evidence.

    Citations carry only a page number, so a cited page counts when any evidence item has that page;
    every evidence page in the open set comes from the question's own filing.
    """
    evidence = {e.page_number for e in q.evidence}
    return bool(cited_pages(answer) & evidence)
