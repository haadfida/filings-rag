"""Answer a benchmark question in one of several modes.

- closed_book: the question alone. Measures what the model knows or guesses without documents.
- oracle: the full text of the evidence page(s) the benchmark marks. The ceiling for retrieval work.
- bm25: the top 5 pages of the named filing by plain BM25. The simplest retrieval baseline.
- routed: the top 5 chunks of the named filing from milestone 3's retrieval (statement routing, then
  re-ranking).
- routed_rewrite: milestone 5. Routing, then searches for the question and three rewrites of it in the
  filing's wording, fused; one chunk per page past the routed ones. The system under test.
"""

from __future__ import annotations

from dataclasses import dataclass

from filings_rag.benchmark import Question
from filings_rag.llm import LLM, Result
from filings_rag.pages import bm25_pages, page_texts


def pipeline(mode: str) -> str:
    """What produced the context for a mode, recorded in each run's config so a resumed run cannot mix
    pipelines. Milestone 4's routed run used statements v1; a resume today would use v2 and be refused."""
    from filings_rag.parse import PARSER_VERSION
    from filings_rag.rewrite import REWRITE_VERSION
    from filings_rag.statements import STATEMENTS_VERSION

    chunks = f"{PARSER_VERSION}|statements-{STATEMENTS_VERSION}|k{ROUTED_K}"
    return {
        "closed_book": "none",
        "oracle": "evidence-pages",
        "bm25": f"bm25-pages|k{BM25_K}",
        "routed": chunks,
        "routed_rewrite": f"{chunks}|rewrite-{REWRITE_VERSION}",
    }[mode]


MODES = ("closed_book", "oracle", "bm25", "routed", "routed_rewrite")
BM25_K = 5
ROUTED_K = 5

SYSTEM = """You answer questions about public companies' financial filings.

Use only the filing excerpts provided. If none are provided, answer from what you know, and say you \
cannot answer if you are not confident. Never invent figures.

Give the answer the question asks for, in the units it asks for, with any calculation shown briefly. \
When you use a figure from an excerpt, cite its page as [p. N]. If the excerpts do not contain what \
is needed, set cannot_answer to true and say what is missing."""

SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "The answer, with brief working and page citations"},
        "cannot_answer": {"type": "boolean"},
    },
    "required": ["answer", "cannot_answer"],
    "additionalProperties": False,
}


@dataclass
class Context:
    pages: list[tuple[str, int]]  # (doc_name, zero-indexed page)
    text: str


def build_context(q: Question, mode: str) -> Context:
    if mode == "closed_book":
        return Context([], "")
    if mode == "oracle":
        seen: dict[tuple[str, int], str] = {}
        for e in q.evidence:
            seen.setdefault((e.doc_name, e.page), e.full_page_text)
        pages = list(seen)
        blocks = [f"[{doc}, p. {page + 1}]\n{text}" for (doc, page), text in seen.items()]
    elif mode == "bm25":
        texts = page_texts(q.doc_name)
        ranked = bm25_pages(q.doc_name, q.question, BM25_K)
        pages = [(q.doc_name, p) for p in ranked]
        blocks = [f"[{q.doc_name}, p. {p + 1}]\n{texts[p]}" for p in ranked]
    elif mode == "routed":
        from filings_rag.retrieve import doc_index

        hits = doc_index(q.doc_name).search("routed", q.question, ROUTED_K)
        pages = list(dict.fromkeys((h.chunk.doc_name, h.chunk.page) for h in hits))
        blocks = [f"[{h.chunk.doc_name}, p. {h.chunk.page + 1}]\n{h.chunk.text}" for h in hits]
    elif mode == "routed_rewrite":
        from filings_rag.retrieve import doc_index
        from filings_rag.rewrite import rewrites

        rw = rewrites(q.question, q.company)
        hits = doc_index(q.doc_name).search_routed_rewrite(q.question, ROUTED_K, rw)
        pages = list(dict.fromkeys((h.chunk.doc_name, h.chunk.page) for h in hits))
        blocks = [f"[{h.chunk.doc_name}, p. {h.chunk.page + 1}]\n{h.chunk.text}" for h in hits]
    else:
        raise ValueError(f"unknown mode {mode!r}")
    return Context(pages, "\n\n---\n\n".join(blocks))


def build_prompt(q: Question, ctx: Context) -> str:
    header = f"Company: {q.company}\nFiling: {q.doc_name}\n"
    if ctx.text:
        return f"{header}\nExcerpts:\n\n{ctx.text}\n\nQuestion: {q.question}"
    return f"{header}\nNo excerpts are provided.\n\nQuestion: {q.question}"


def answer(llm: LLM, q: Question, mode: str, model: str, effort: str) -> tuple[Context, Result]:
    ctx = build_context(q, mode)
    return ctx, llm.json(model=model, system=SYSTEM, user=build_prompt(q, ctx), schema=SCHEMA, effort=effort)


def fingerprint(mode: str) -> str:
    """A hash of everything besides the model settings that shapes a run's answers and grades: the answer
    and judge prompts, and the retrieval constants. Stored in each run's config, so resuming a run name
    after any of these change is refused instead of mixing two systems in one summary."""
    import hashlib
    import inspect
    import json

    from filings_rag import judge, retrieve

    parts = [
        SYSTEM,
        json.dumps(SCHEMA, sort_keys=True),
        inspect.getsource(build_prompt),
        inspect.getsource(build_context),
        judge.PROMPT_FINGERPRINT,
        pipeline(mode),
    ]
    if mode.startswith("routed"):
        parts += [
            retrieve.EMBED_MODEL,
            retrieve.RERANK_MODEL,
            f"{retrieve.RERANK_POOL}|{retrieve.RERANK_CHARS}|{retrieve.RRF_K}|{retrieve.EMBED_MAX_CHARS}",
            inspect.getsource(retrieve.Index.search_routed),
            inspect.getsource(retrieve.Index.search_routed_rewrite),
            inspect.getsource(retrieve.Index.search_rerank),
        ]
    return hashlib.sha256("\x1e".join(parts).encode()).hexdigest()[:12]
