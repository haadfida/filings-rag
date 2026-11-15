"""Answer a benchmark question in one of three baseline modes.

- closed_book: the question alone. Measures what the model knows or guesses without documents.
- oracle: the full text of the evidence page(s) the benchmark marks. The ceiling for retrieval work.
- bm25: the top 5 pages of the named filing by plain BM25. The simplest retrieval baseline.
- routed: the top 5 chunks of the named filing from milestone 3's retrieval (statement routing, then
  re-ranking). The system under test.
"""

from __future__ import annotations

from dataclasses import dataclass

from filings_rag.benchmark import Question
from filings_rag.llm import LLM, Result
from filings_rag.pages import bm25_pages, page_texts

MODES = ("closed_book", "oracle", "bm25", "routed")
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
