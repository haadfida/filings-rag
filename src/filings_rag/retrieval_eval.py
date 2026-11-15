"""Measure retrieval against the benchmark's evidence pages. No model calls.

For each question, a method returns ranked chunks. A question is a hit at k when any of the top k chunks
comes from a page the benchmark marks as evidence. Reported for k = 1, 3, 5 and 10, with mean reciprocal
rank of the first evidence chunk (MRR@10) and the characters of context the top 5 would hand the model.

Baseline: milestone 1's page-level BM25, where the unit is a whole page.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable

from filings_rag.benchmark import Question, load_questions, split_of
from filings_rag.pages import bm25_pages, page_texts
from filings_rag.retrieve import Hit, corpus_index, doc_index, embed_query

KS = (1, 3, 5, 10)


def _evidence(q: Question) -> set[tuple[str, int]]:
    return {(e.doc_name, e.page) for e in q.evidence}


def _score(ranked: list[list[tuple[str, int]]], gold: list[set], context: list[int]) -> dict:
    n = len(ranked)
    out: dict = {
        f"hit@{k}": round(sum(bool(set(r[:k]) & g) for r, g in zip(ranked, gold, strict=True)) / n, 3)
        for k in KS
    }
    rr = []
    for r, g in zip(ranked, gold, strict=True):
        first = next((i for i, p in enumerate(r[:10]) if p in g), None)
        rr.append(0.0 if first is None else 1.0 / (first + 1))
    out["mrr@10"] = round(statistics.mean(rr), 3)
    out["context_chars_top5"] = int(statistics.median(context))
    return out


def _run(questions: list[Question], search: Callable[[Question], list[Hit]]) -> dict:
    ranked, gold, context = [], [], []
    for q in questions:
        hits = search(q)
        ranked.append([(h.chunk.doc_name, h.chunk.page) for h in hits])
        gold.append(_evidence(q))
        context.append(sum(len(h.chunk.text) for h in hits[:5]))
    return _score(ranked, gold, context)


def evaluate(
    split: str = "dev", methods: tuple[str, ...] = ("bm25", "dense", "hybrid"), open_setting: bool = True
) -> dict:
    questions = [q for q in load_questions() if split == "all" or split_of(q) == split]
    dense = bool(set(methods) - {"bm25"})
    qvecs = {q.id: embed_query(q.question) for q in questions} if dense else {}

    # Baseline: whole pages ranked by BM25 within the named filing.
    ranked, gold, context = [], [], []
    for q in questions:
        pages = bm25_pages(q.doc_name, q.question, 10)
        ranked.append([(q.doc_name, p) for p in pages])
        gold.append(_evidence(q))
        texts = page_texts(q.doc_name)
        context.append(sum(len(texts[p]) for p in pages[:5]))
    result: dict = {
        "split": split,
        "questions": len(questions),
        "document_given": {"bm25_pages (milestone 1)": _score(ranked, gold, context)},
    }

    for m in methods:
        if m == "routed_rewrite":  # milestone 5: needs the question's rewrites (one cached model call each)
            from filings_rag.rewrite import rewrites

            def search(q: Question) -> list[Hit]:
                rw = rewrites(q.question, q.company)
                return doc_index(q.doc_name).search_routed_rewrite(q.question, 10, rw, qvecs.get(q.id))

        else:

            def search(q: Question, m: str = m) -> list[Hit]:
                return doc_index(q.doc_name, dense).search(m, q.question, 10, qvecs.get(q.id))

        result["document_given"][f"{m}_chunks"] = _run(questions, search)

    if open_setting:
        docs = tuple(sorted({q.doc_name for q in load_questions()}))
        index = corpus_index(docs, dense)
        result["open"] = {"filings": len(docs), "chunks": len(index.chunks)}
        for m in (m for m in methods if not m.startswith("routed")):  # routing needs the named filing
            scores = _run(questions, lambda q, m=m: index.search(m, q.question, 10, qvecs.get(q.id)))
            right_doc = []
            for q in questions:
                hits = index.search(m, q.question, 5, qvecs.get(q.id))
                right_doc.append(any(h.chunk.doc_name == q.doc_name for h in hits))
            scores["right_filing_in_top5"] = round(sum(right_doc) / len(right_doc), 3)
            result["open"][f"{m}_chunks"] = scores
    return result
