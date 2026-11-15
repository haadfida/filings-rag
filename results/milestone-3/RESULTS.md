# Milestone 3: retrieval

Run on 15 Nov 2026. No model calls; cost $0. Embedding the 65,423 chunks took 67 minutes on a CPU.
Reproduce with `filings-rag retrieval-eval --split test`.

## Setting

- **Filing given.** FinanceBench names the filing each question is about, so retrieval searches that
  filing only.
- **Hit at k.** A question is a hit at k when one of the top k chunks comes from a page the benchmark
  marks as evidence.
- **Context.** The median number of characters the top 5 results would hand the model.
- **Tuning.** Methods were designed and tuned on the 50 dev questions; the 100 test questions were run
  once at the end.

## Results

| Method | Dev hit@1 | Dev hit@5 | **Test hit@1** | **Test hit@5** | Test hit@10 | Test MRR@10 | Context (top 5) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 over whole pages (milestone 1) | 12% | 26% | 16% | 28% | 36% | 0.21 | 21,090 |
| BM25 over chunks | 12% | 20% | 18% | 28% | 32% | 0.21 | 4,479 |
| Dense (bge-small) | 14% | 38% | 19% | 45% | 54% | 0.29 | 3,336 |
| Hybrid (BM25 + dense, RRF) | 12% | 34% | 17% | 36% | 41% | 0.24 | 4,220 |
| Dense + BM25, cross-encoder re-ranked | 18% | 40% | 23% | 42% | 50% | 0.31 | 4,116 |
| **Statement routing + re-ranking** | **56%** | **74%** | **52%** | **73%** | **75%** | **0.60** | 4,781 |

## What worked, and what did not

**Statement routing is the step change: test hit@5 rises from 28% to 73%.**
- **Diagnosis.** Most dev misses had the same cause. The question needs a primary financial statement
  (balance sheet, income statement, cash flow statement), and search returned notes or management's
  discussion that use the same words.
- **Router.** `src/filings_rag/statements.py` reads which statements a question names or implies
  ("quick ratio" means the balance sheet; "capital expenditure" means cash flows). It finds those
  statement pages in the filing by their titles, keeping the titled page with the most table rows, and
  puts their table chunks first.
- **Coverage.** A page titled as each statement was found in all 64 annual reports. *Correction
  (milestone 5): many of those pages were look-alikes, not the primary statement; see
  [milestone 5](../milestone-5/RESULTS.md).*
- **Held up out of sample.** The cue lists were written with the dev misses in view, but the test score
  (73%) matches dev (74%).

**Hybrid fusion hurt.** Adding BM25 to dense lowered test hit@5 from 45% to 36%.
- Questions use concepts ("capital expenditure") while filings use line-item labels ("Purchases of
  property, plant and equipment"), so keyword ranking adds noise.
- Weighting dense twice as heavily did not fix it on dev.

**Re-ranking was neutral.** A small cross-encoder (`ms-marco-MiniLM-L-6-v2`) helped on dev (hit@5 40%
against 38%) but not on test (42% against 45%). It stays in the routed pipeline for the non-routed
questions only because routing was built on it. Whether plain dense does as well there is an open check.

**Chunks are a quarter the size of pages.** Top-5 context fell from about 21,000 characters to under
5,000, which matters for cost and for how much the model has to read.

## Limits

- **One marked page per fact.** Filings repeat figures (a statement and a summary table), so a
  correct page that is not the marked one counts as a miss. These numbers are therefore lower bounds.
- **27% of test questions still miss in the top 5.** Most are questions with no statement cue, such as
  acquisitions, segment detail or litigation, where dense search alone has to find a note.
- **Search across all 84 filings at once** is built (`--open`) but not yet reported.
- **Dev is small.** 50 questions, so a 2-point difference on dev is one question.

## Next

Milestone 4 answers questions from the routed top 5 with Opus 5.5 and reports plain and grounded accuracy,
against the baselines: closed book 74.0% correct and 0% grounded, oracle 95.3%, page BM25 46.0%.
