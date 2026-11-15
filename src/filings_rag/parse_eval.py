"""Measure parsing quality against the benchmark, with no model calls.

Two measures, each computed for the plain PyMuPDF text and for the table-aware parser:

evidence recovery
    For each of the 189 evidence passages, the share of its character 8-grams (whitespace removed,
    lower case) found in our text of the marked page. Ignoring whitespace matters: the benchmark's own
    evidence text glues words together on some filings ("consolidatedbalancesheets"). A passage counts
    as recovered at 90% or more.

row integrity
    Metrics questions name the exact line items they used, e.g. "a single line item named: Total net
    sales". A line item counts as intact when one line of our text holds both the label and a number,
    which is what a reader or a retriever needs. Labels are taken from the justifications (92 in all).
"""

from __future__ import annotations

import re
from collections.abc import Callable

from filings_rag.benchmark import Question, load_questions
from filings_rag.pages import page_texts
from filings_rag.parse import parse_document

_LABEL = re.compile(
    r"line item(?: name)?(?:, as seen in the 10K,)? (?:was|named)[:\s]+(.+?)(?:\.\s|\.$|\n)", re.IGNORECASE
)
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_MOJIBAKE = {"â": "-", "Â": " ", "’": "'", "–": "-", "—": "-"}


def _squash(text: str) -> str:
    for bad, good in _MOJIBAKE.items():
        text = text.replace(bad, good)
    # Whitespace and our own column separators carry no content; drop both before comparing.
    return re.sub(r"[\s|]+", "", text.lower())


def _grams(text: str, n: int = 8) -> set[str]:
    s = _squash(text)
    return {s[i : i + n] for i in range(max(0, len(s) - n + 1))}


def evidence_recovery(page_text: Callable[[str, int], str], questions: list[Question]) -> dict:
    scores = []
    for q in questions:
        for e in q.evidence:
            want = _grams(e.text)
            have = _grams(page_text(e.doc_name, e.page))
            scores.append(len(want & have) / len(want) if want else 1.0)
    n = len(scores)
    return {
        "items": n,
        "recovered_90": sum(s >= 0.9 for s in scores),
        "share": round(sum(s >= 0.9 for s in scores) / n, 3),
    }


def line_item_labels(q: Question) -> list[str]:
    labels = []
    for raw in _LABEL.findall(q.justification or ""):
        label = raw.strip().rstrip(".")
        for bad, good in _MOJIBAKE.items():
            label = label.replace(bad, good)
        labels.append(label)
    return labels


def _norm_label(text: str) -> str:
    text = text.lower()
    for bad, good in _MOJIBAKE.items():
        text = text.replace(bad.lower(), good)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def row_integrity(page_lines: Callable[[str, int], list[str]], questions: list[Question]) -> dict:
    found = intact = total = 0
    misses: list[str] = []
    for q in questions:
        for label in line_item_labels(q):
            total += 1
            key = _norm_label(label)
            lines = [ln for e in q.evidence for ln in page_lines(e.doc_name, e.page)]
            hits = [ln for ln in lines if key in _norm_label(ln)]
            found += bool(hits)
            ok = any(_NUM.search(_norm_label(ln).replace(key, "", 1)) for ln in hits)
            intact += ok
            if hits and not ok:
                misses.append(f"{q.id}: {label}")
    return {
        "labels": total,
        "label_on_page": found,
        "intact": intact,
        "share_of_found": round(intact / found, 3) if found else None,
        "examples_not_intact": misses[:10],
    }


def compare() -> dict:
    questions = load_questions()
    metrics = [q for q in questions if q.question_type == "metrics-generated"]

    def plain_text(doc: str, page: int) -> str:
        return page_texts(doc)[page]

    def plain_lines(doc: str, page: int) -> list[str]:
        return plain_text(doc, page).splitlines()

    def rows_text(doc: str, page: int) -> str:
        return parse_document(doc)[page].text

    def rows_lines(doc: str, page: int) -> list[str]:
        return [ln.text for ln in parse_document(doc)[page].lines]

    return {
        "plain": {
            "evidence_recovery": evidence_recovery(plain_text, questions),
            "row_integrity": row_integrity(plain_lines, metrics),
        },
        "rows": {
            "evidence_recovery": evidence_recovery(rows_text, questions),
            "row_integrity": row_integrity(rows_lines, metrics),
        },
    }
