"""Retrieval over chunks: BM25, dense vectors, and a hybrid of the two by reciprocal rank fusion.

Two settings, as in the design:
- document given: search only the filing the question names (FinanceBench names it).
- open: search every chunk of all 84 filings, so finding the right filing is part of the task.

Every chunk is indexed with a short header naming the company, filing type and period, so "3M's FY2018
capital expenditure" can match the right filing in the open setting.

Embeddings: BAAI/bge-small-en-v1.5 (384 dimensions) run locally through fastembed, so indexing costs
nothing and needs no API key. Vectors are normalised and cached per filing as .npy files; at 65k chunks a
plain NumPy matrix is fast enough, so no vector database is needed yet.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import cache, lru_cache

import numpy as np
from rank_bm25 import BM25Okapi

from filings_rag.benchmark import DATA_DIR, load_documents
from filings_rag.chunk import Chunk, chunk_document
from filings_rag.pages import tokenize
from filings_rag.parse import PARSER_VERSION

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "  # BGE's query instruction
CACHE = DATA_DIR.parent / "cache"
EMB_DIR = CACHE / f"emb-{EMBED_MODEL.replace('/', '_')}-{PARSER_VERSION}-t700"
RRF_K = 60
RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
RERANK_POOL = 25  # candidates taken from each of BM25 and dense before re-ranking
RERANK_CHARS = 1000
# Number-heavy table text tokenises into many word pieces, which makes a 12-layer model slow on a CPU.
# Dense vectors see the first EMBED_MAX_CHARS characters (header, caption, units and first rows); BM25
# always sees the whole chunk.
EMBED_MAX_CHARS = 700


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float


@cache
def header(doc_name: str) -> str:
    d = load_documents().get(doc_name)
    if d is None:
        return doc_name
    return f"{d.company} {d.doc_type.upper()} {d.period} ({doc_name})"


def indexed_text(c: Chunk) -> str:
    return f"{header(c.doc_name)}\n{c.text}"


@lru_cache(maxsize=1)
def _embedder():
    from fastembed import TextEmbedding

    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    return TextEmbedding(EMBED_MODEL, cache_dir=str(CACHE / "models"))


@lru_cache(maxsize=1)
def _reranker():
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    return TextCrossEncoder(RERANK_MODEL, cache_dir=str(CACHE / "models"))


def embed_documents(texts: list[str]) -> np.ndarray:
    """Normalised embeddings, in input order. Texts are embedded shortest first to limit padding."""
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    out = np.zeros((len(texts), 384), dtype=np.float32)
    clipped = [texts[i][:EMBED_MAX_CHARS] for i in order]
    for i, vec in zip(order, _embedder().embed(clipped, batch_size=32), strict=True):
        out[i] = vec
    return out / np.linalg.norm(out, axis=1, keepdims=True).clip(min=1e-9)


def embed_query(text: str) -> np.ndarray:
    return embed_documents([QUERY_PREFIX + text])[0]


def doc_vectors(doc_name: str) -> np.ndarray:
    """Embeddings of a filing's chunks, in chunk order, computed once and cached."""
    path = EMB_DIR / f"{doc_name}.npy"
    ids_path = EMB_DIR / f"{doc_name}.ids.json"
    chunks = chunk_document(doc_name)
    ids = [c.id for c in chunks]
    if path.exists() and ids_path.exists() and json.loads(ids_path.read_text()) == ids:
        return np.load(path)
    vecs = embed_documents([indexed_text(c) for c in chunks])
    EMB_DIR.mkdir(parents=True, exist_ok=True)
    np.save(path, vecs)
    ids_path.write_text(json.dumps(ids))
    return vecs


class Index:
    """BM25 and dense search over a fixed list of chunks."""

    def __init__(self, chunks: list[Chunk], vectors: np.ndarray | None) -> None:
        self.chunks = chunks
        self.vectors = vectors
        self.bm25 = BM25Okapi([tokenize(indexed_text(c)) or ["_empty_"] for c in chunks])

    def _top(self, scores: np.ndarray, k: int) -> list[Hit]:
        k = min(k, len(scores))
        idx = np.argpartition(-scores, k - 1)[:k]
        idx = idx[np.argsort(-scores[idx])]
        return [Hit(self.chunks[i], float(scores[i])) for i in idx]

    def search_bm25(self, query: str, k: int) -> list[Hit]:
        return self._top(np.asarray(self.bm25.get_scores(tokenize(query))), k)

    def search_dense(self, query: str, k: int, qvec: np.ndarray | None = None) -> list[Hit]:
        if self.vectors is None:
            raise RuntimeError("this index was built without vectors (keyword search only)")
        q = embed_query(query) if qvec is None else qvec
        return self._top(self.vectors @ q, k)

    def search_hybrid(
        self, query: str, k: int, pool: int = 50, qvec: np.ndarray | None = None, dense_weight: float = 1.0
    ) -> list[Hit]:
        """Reciprocal rank fusion of the BM25 and dense rankings (each cut to `pool`)."""
        fused: dict[str, float] = {}
        by_id: dict[str, Chunk] = {}
        rankings = (
            (self.search_bm25(query, pool), 1.0),
            (self.search_dense(query, pool, qvec), dense_weight),
        )
        for ranking, weight in rankings:
            for rank, hit in enumerate(ranking):
                fused[hit.chunk.id] = fused.get(hit.chunk.id, 0.0) + weight / (RRF_K + rank + 1)
                by_id[hit.chunk.id] = hit.chunk
        best = sorted(fused, key=fused.get, reverse=True)[:k]
        return [Hit(by_id[i], fused[i]) for i in best]

    def search_rerank(self, query: str, k: int, qvec: np.ndarray | None = None) -> list[Hit]:
        """Union of the top BM25 and dense candidates, re-scored by a cross-encoder."""
        cands: dict[str, Chunk] = {}
        for hit in self.search_bm25(query, RERANK_POOL) + self.search_dense(query, RERANK_POOL, qvec):
            cands.setdefault(hit.chunk.id, hit.chunk)
        chunks = list(cands.values())
        docs = [indexed_text(c)[:RERANK_CHARS] for c in chunks]
        scores = list(_reranker().rerank(query, docs, batch_size=16))
        order = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)[:k]
        return [Hit(chunks[i], float(scores[i])) for i in order]

    def search_routed(
        self, query: str, k: int, qvec: np.ndarray | None = None, max_routed: int = 4
    ) -> list[Hit]:
        """Statement routing, then re-ranking: chunks of the primary statements the question needs come first.

        Only for a single filing's index (the document-given setting).
        """
        from filings_rag.statements import statement_pages, statements_for

        doc = self.chunks[0].doc_name if self.chunks else ""
        pages = {p for name in statements_for(query) for p in statement_pages(doc).get(name, [])}
        routed = [c for c in self.chunks if c.page in pages and c.kind == "table"]
        if routed and self.vectors is not None:
            q = embed_query(query) if qvec is None else qvec
            pos = {c.id: i for i, c in enumerate(self.chunks)}
            routed.sort(key=lambda c: -float(self.vectors[pos[c.id]] @ q))
        head = [Hit(c, 1.0) for c in routed[:max_routed]]
        seen = {h.chunk.id for h in head}
        rest = [h for h in self.search_rerank(query, k + len(head), qvec) if h.chunk.id not in seen]
        return (head + rest)[:k]

    def search(self, method: str, query: str, k: int, qvec: np.ndarray | None = None) -> list[Hit]:
        if method == "bm25":
            return self.search_bm25(query, k)
        if method == "dense":
            return self.search_dense(query, k, qvec)
        if method == "hybrid":
            return self.search_hybrid(query, k, qvec=qvec)
        if method == "hybrid_dense2":
            return self.search_hybrid(query, k, qvec=qvec, dense_weight=2.0)
        if method == "rerank":
            return self.search_rerank(query, k, qvec)
        if method == "routed":
            return self.search_routed(query, k, qvec)
        raise ValueError(f"unknown method {method!r}")


@lru_cache(maxsize=128)
def doc_index(doc_name: str, dense: bool = True) -> Index:
    return Index(chunk_document(doc_name), doc_vectors(doc_name) if dense else None)


def corpus_index(doc_names: tuple[str, ...], dense: bool = True) -> Index:
    """All chunks of the given filings in one index. With dense=False no embeddings are computed."""
    chunks = [c for d in doc_names for c in chunk_document(d)]
    vectors = np.vstack([doc_vectors(d) for d in doc_names]) if dense else None
    return Index(chunks, vectors)
