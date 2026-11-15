"""Page text from the filings, and the plain BM25 baseline over whole pages.

This is deliberately naive: one chunk per page, PyMuPDF's plain text, no table handling. It is the
"simplest thing" baseline that milestones 2 and 3 have to beat. Page text is cached as JSON.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache

import pymupdf
from rank_bm25 import BM25Okapi

from filings_rag.benchmark import DATA_DIR, pdf_path
from filings_rag.cachefile import PDF_LOCK, atomic_write_text, lock_for

CACHE_DIR = DATA_DIR.parent / "cache" / "pages"
_TOKEN = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")


def page_texts(doc_name: str) -> list[str]:
    """Text of every page, zero-indexed like the benchmark's evidence pages."""
    cache = CACHE_DIR / f"{doc_name}.json"
    with lock_for(f"pages:{doc_name}"):
        if cache.exists():
            return json.loads(cache.read_text(encoding="utf-8"))
        with PDF_LOCK, pymupdf.open(pdf_path(doc_name)) as pdf:
            texts = [page.get_text() for page in pdf]
        atomic_write_text(cache, json.dumps(texts))
        return texts


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


@lru_cache(maxsize=16)
def _index(doc_name: str) -> BM25Okapi:
    return BM25Okapi([tokenize(t) or ["_empty_"] for t in page_texts(doc_name)])


def bm25_pages(doc_name: str, query: str, k: int = 5) -> list[int]:
    """Zero-indexed pages of `doc_name` ranked by BM25 against the query, best first."""
    scores = _index(doc_name).get_scores(tokenize(query))
    return sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
