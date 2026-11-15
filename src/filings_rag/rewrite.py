"""Rewrite an analyst's question into searches in the filing's own wording.

Questions say "capex" or "did they retain card members"; filings say "Purchases of property, plant and
equipment" or "card member retention". A small model writes a few such searches, and each is run through
retrieval alongside the original question. Rewrites are cached on disk, so a question is rewritten once.

The rewrites used for the published results ship with the package (`rewrites-v1.jsonl`, hashed keys and
queries only), so the retrieval numbers reproduce from a fresh clone without an API key. Change the model
or the prompt and PROMPT_FINGERPRINT changes; a test then fails until REWRITE_VERSION is bumped.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from filings_rag.benchmark import DATA_DIR
from filings_rag.llm import LLM

REWRITE_MODEL = "claude-haiku-5-5"
REWRITE_VERSION = "v1"
CACHE_FILE = DATA_DIR.parent / "cache" / f"rewrites-{REWRITE_VERSION}.jsonl"
SHIPPED_FILE = Path(__file__).with_name(f"rewrites-{REWRITE_VERSION}.jsonl")
N_QUERIES = 3

SYSTEM = f"""You help search a company's SEC filing (10-K, 10-Q, 8-K or earnings release).

Given an analyst's question, write {N_QUERIES} short search queries in the wording the filing itself would \
use: exact financial statement line items, note or section titles, and the phrases management uses in \
MD&A. Do not answer the question. Each query is one line of at most 12 words."""

PROMPT_FINGERPRINT = hashlib.sha256(f"{REWRITE_MODEL}|{SYSTEM}".encode()).hexdigest()[:12]

SCHEMA = {
    "type": "object",
    "properties": {"queries": {"type": "array", "items": {"type": "string"}}},
    "required": ["queries"],
    "additionalProperties": False,
}

_lock = threading.Lock()
_cache: dict[str, list[str]] | None = None


def _key(company: str, question: str) -> str:
    return hashlib.sha256(f"{REWRITE_VERSION}|{company}|{question}".encode()).hexdigest()[:16]


def _load() -> dict[str, list[str]]:
    global _cache
    if _cache is None:
        _cache = {}
        for path in (SHIPPED_FILE, CACHE_FILE):
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        row = json.loads(line)
                        if row["queries"]:
                            _cache[row["key"]] = row["queries"]
    return _cache


def rewrites(question: str, company: str, llm: LLM | None = None) -> list[str]:
    """Search queries for a question, from the cache or one call to the rewrite model."""
    key = _key(company, question)
    with _lock:
        if key in _load():
            return _cache[key]
    res = (llm or LLM()).json(
        model=REWRITE_MODEL,
        system=SYSTEM,
        user=f"Company: {company}\nQuestion: {question}",
        schema=SCHEMA,
        effort="low",
        max_tokens=2000,
    )
    queries = [q.strip() for q in (res.data or {}).get("queries", []) if q.strip()][:N_QUERIES]
    if not queries:  # refused or cut off: fail, so the answer is recorded as an error and retried
        raise RuntimeError(f"rewrite returned no queries (stop_reason={res.stop_reason})")
    with _lock:
        _cache[key] = queries
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with CACHE_FILE.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "key": key,
                        "company": company,
                        "question": question,
                        "queries": queries,
                        "cost": res.cost,
                    }
                )
                + "\n"
            )
    return queries
