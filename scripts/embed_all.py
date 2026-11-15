"""Embed every chunk of the benchmark's filings, dev-split filings first. Run once; results are cached."""

import time

from filings_rag.benchmark import load_questions, split_of
from filings_rag.retrieve import doc_vectors

qs = load_questions()
dev = sorted({q.doc_name for q in qs if split_of(q) == "dev"})
rest = sorted({q.doc_name for q in qs} - set(dev))
start = time.time()
for n, doc in enumerate(dev + rest, 1):
    v = doc_vectors(doc)
    print(f"{n}/{len(dev) + len(rest)} {doc} {v.shape[0]} chunks, {time.time() - start:.0f}s", flush=True)
