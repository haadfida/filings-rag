# Milestone 1: baselines and judge validation

Run on 14 Nov 2026. All three baselines use `claude-opus-5-5` at effort `medium`, graded by `claude-opus-5-5`
at effort `medium`. One run per question, so no variance estimate yet. Total cost: $13.77.

## Scores

Share of answers graded correct. "Clean" leaves out the three questions whose reference answer contradicts
its own working (see DESIGN.md, section 2).

| Baseline | What the model sees | Dev (50) | Test (100) | All (150) | All, clean | Refusals | Evidence page given |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Oracle | The benchmark's evidence page(s) | 98% | 94% | **95.3%** | 95.2% | 0% | 100% |
| Closed book | The question only | 82% | 70% | **74.0%** | 73.5% | 9% | – |
| BM25, top 5 pages | 5 pages of the named filing, by keyword search | 52% | 43% | **46.0%** | 47.2% | 45% | 27% |

Cost per question, answer plus grading: oracle $0.021, closed book $0.020, BM25 $0.045. Median latency
3.8 s, 6.2 s and 5.4 s.

## Judge validation

The judge graded 150 of the paper's human-labelled answers, 50 per human label, sampled with a fixed seed.

| | |
| --- | --- |
| Agreement with the human label | **90%** (135 of 150) |
| Cohen's kappa | **0.85** |
| Cost | $0.90 |

| Human \ Judge | correct | incorrect | refusal |
| --- | ---: | ---: | ---: |
| correct | 47 | 3 | 0 |
| incorrect | 3 | 41 | 6 |
| refusal | 1 | 2 | 47 |

The largest disagreement is definitional. In six cases people graded an output as incorrect where the
judge called it a refusal. Each of those outputs was not an answer at all: pasted filing text, a greeting,
or "cannot calculate". Our rubric says a non-answer is a refusal, while the paper's reviewers counted
garbage output as incorrect. Either convention is defensible; this one should be aligned with the paper's
before the headline run (see next steps). The other nine disagreements are close calls in both directions.

## What this shows

**1. Opus 5.5 answers 74% of FinanceBench from memory.**
- With no documents at all, it got 46 of the 50 metrics questions right (figures such as 3M's 2018
  capital spending). The benchmark and its filings have been public since 2023.
- So a raw accuracy score cannot tell retrieval from recall. A retrieval system needs a second metric:
  **grounded accuracy**, meaning correct *and* supported by a cited page that holds the evidence.
- This changes the plan for milestone 4 (see next steps).

**2. Plain keyword search is worse than no documents.**
- BM25 put an evidence page in the top 5 for only 41 of 150 questions (27%).
- The prompt tells the model to answer only from the excerpts, so when retrieval missed, it said so
  instead of falling back on memory: 66 of its 67 refusals came after a miss.
- That behaviour is right for a citation-backed product, and it makes retrieval the bottleneck: the gap
  between 46% and the 95% ceiling is almost all retrieval. Milestones 2 and 3 (table-aware parsing,
  hybrid retrieval) target it.

**3. The ceiling is 95%, and the misses are mostly method choices.** The seven oracle misses:

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

1. **Add grounded accuracy** to the runner: an answer counts as grounded when it is correct and cites a
   page that holds the evidence. Report it next to plain accuracy from milestone 4 on.
2. **Align the "non-answer" rule** with the paper's reviewers (non-answers are incorrect, explicit
   declines are refusals) and re-run the judge validation, about $1.
3. **Milestone 2:** table-aware parsing, measured by whether each evidence text is recoverable from its
   parsed page.
4. **Milestone 3:** hybrid retrieval, measured by evidence-page hit rate on the dev split (BM25 baseline:
   13 of 50).

## Files

- `oracle.json`, `closed_book.json`, `bm25.json`: run summaries by split, cost and latency.
- `judge-validation.json`: agreement, kappa and confusion counts.
- Per-question answers and grades stay in `runs/`, which is not committed.
