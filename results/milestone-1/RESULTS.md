# Milestone 1: baselines and judge validation

Run on 14 Nov 2026. All three baselines use `claude-opus-5-5` at effort `medium`, graded by `claude-opus-5-5`
at effort `medium` with judge rubric v1. One run per question, so no variance estimate yet. Total cost:
$13.77 for the runs, plus $0.92 to re-validate the judge with rubric v2.

## Scores

Share of answers graded correct. "Clean" leaves out the three questions whose reference answer contradicts
its own working (see DESIGN.md, section 2). **Grounded** means correct *and* citing a page the benchmark
marks as evidence; it is what separates retrieval from what the model remembers.

| Baseline | Correct | Grounded | Cites any page |
| --- | ---: | ---: | ---: |
| Oracle | 95.3% | **95.3%** | 100% |
| Closed book | 74.0% | **0%** | 0% |
| BM25, top 5 pages | 46.0% | **22.7%** | 97% |

| Baseline | What the model sees | Dev (50) | Test (100) | All (150) | All, clean | Refusals | Evidence page given |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Oracle | The benchmark's evidence page(s) | 98% | 94% | **95.3%** | 95.2% | 0% | 100% |
| Closed book | The question only | 82% | 70% | **74.0%** | 73.5% | 9% | – |
| BM25, top 5 pages | 5 pages of the named filing, by keyword search | 52% | 43% | **46.0%** | 47.2% | 45% | 27% |

Cost per question, answer plus grading: oracle $0.021, closed book $0.020, BM25 $0.045. Median latency
3.8 s, 6.2 s and 5.4 s.

## Judge validation

The judge graded 150 of the paper's human-labelled answers, 50 per human label, sampled with a fixed seed.
The same sample was graded with two versions of the rubric.

| Rubric | Agreement with people | Cohen's kappa | Cost |
| --- | ---: | ---: | ---: |
| v1 | 90% (135 of 150) | 0.85 | $0.90 |
| **v2** | **94% (141 of 150)** | **0.91** | $0.92 |
| v2, fresh sample (milestone 5) | 92% (138 of 150) | 0.88 | $0.94 |

v2 was written after reading v1's disagreements on this same sample, so 94% is in-sample. On 150 other
human-labelled answers (seed 11, excluding this sample) v2 agrees 92% of the time, kappa 0.88; that is the
figure to quote. See `results/milestone-5/judge-validation-v2-fresh.json`.

v1 graded non-answers (pasted filing text, a greeting, working that stops without a result) as refusals,
where the paper's reviewers graded them incorrect. v2 grades them incorrect and keeps "refusal" for an
explicit decline. That removed five of the six cases where people said incorrect and the judge said
refusal. v2 is the rubric from here on.

v2 confusion counts:

| Human \ Judge | correct | incorrect | refusal |
| --- | ---: | ---: | ---: |
| correct | 47 | 3 | 0 |
| incorrect | 2 | 47 | 1 |
| refusal | 1 | 2 | 47 |

The nine remaining disagreements are close calls in both directions, such as a sign convention people
accepted and the judge did not. The baseline answers above were graded with v1. The change affects
non-answers only, and Opus's answers are well formed, so a large shift is unlikely. They will be
re-graded with v2 at the next full run so every published number uses one rubric.

## What this shows

**1. Opus 5.5 answers 74% of FinanceBench from memory.**
- With no documents at all, it got 46 of the 50 metrics questions right (figures such as 3M's 2018
  capital spending). The benchmark and its filings have been public since 2023.
- So a raw accuracy score cannot tell retrieval from recall. A retrieval system needs a second metric:
  **grounded accuracy**, meaning correct *and* supported by a cited page that holds the evidence.
- This changes the plan for milestone 4 (see next steps).

**2. Grounding halves the BM25 score, and the strict definition undercounts it.**
- BM25 is 46% correct but only 22.7% grounded.
- All 35 correct-but-ungrounded answers came from questions where retrieval missed the evidence page.
  The model then cited a different page, typically a summary table that repeats the figure.
- So "cites an evidence page" is strict: the benchmark marks one page, while filings repeat key figures.
  A fairer check, that the cited page contains the reference figure, is a next step.

**3. Plain keyword search is worse than no documents.**
- BM25 put an evidence page in the top 5 for only 41 of 150 questions (27%).
- The prompt tells the model to answer only from the excerpts, so when retrieval missed, it said so
  instead of falling back on memory: 66 of its 67 refusals came after a miss.
- That behaviour is right for a citation-backed product, and it makes retrieval the bottleneck: the gap
  between 46% and the 95% ceiling is almost all retrieval. Milestones 2 and 3 (table-aware parsing,
  hybrid retrieval) target it.

**4. The ceiling is 95%, and the misses are mostly method choices.** The seven oracle misses:

| Question | What happened |
| --- | --- |
| `00540` | Used average inventory (12.1x); the reference uses year-end inventory (9.5x) |
| `05718` | $0.389bn against a reference of $0.40bn, 2.75% off, outside the judge's tolerance |
| `00585` | Same magnitudes, opposite signs on the effective tax rate; people graded a GPT-4 answer with the same reversal as correct |
| `00790`, `02419` | Judgement questions where the model reached the opposite conclusion from the reference |
| `01911` | Gave a 0.03x coverage ratio where the reference says EBIT is negative, so zero |
| `00283` | Read $700M as the total cost where the reference reads it as 90% already incurred |

Questions `00540` and `00585` look like ambiguous references rather than model errors; they go on the
review list with the three known contradictory keys.

## Next steps

1. Done: grounded accuracy is in every run summary, from saved answers and with no API calls.
2. Done: judge rubric v2 (94% in-sample, 92% and kappa 0.88 on a fresh sample).
3. **Check cited pages for the figure**, so citations to a page that repeats the evidence also count as
   grounded. Report both definitions.
4. **Milestone 2:** table-aware parsing, measured by whether each evidence text is recoverable from its
   parsed page.
5. **Milestone 3:** hybrid retrieval, measured by evidence-page hit rate on the dev split (BM25 baseline:
   13 of 50).

## Files

- `oracle.json`, `closed_book.json`, `bm25.json`: run summaries by split, cost and latency.
- `judge-validation-v1.json`, `judge-validation-v2.json`: agreement, kappa and confusion counts per rubric.
- Per-question answers and grades stay in `runs/`, which is not committed.
