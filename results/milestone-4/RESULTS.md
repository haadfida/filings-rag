# Milestone 4: answering from routed retrieval

Run on 15 Nov 2026. Answers from `claude-opus-5-5` at effort `medium`, given the top 5 chunks of milestone 3's
retrieval (statement routing, then re-ranking) within the named filing. Graded by `claude-opus-5-5` at
effort `medium` with judge rubric v2. To keep the comparison fair, the closed-book and BM25 baselines were
re-graded with rubric v2 on their saved milestone 1 answers. The oracle keeps its v1 grades: it has no
refusals, which is the only label the rubric change affects.

Cost: $3.84 for the routed run and $1.92 to re-grade the two baselines. One run per question, so there is
no variance estimate yet. Reproduce with `filings-rag run --mode routed --split all`.

## Scores

**Grounded** means correct *and* citing a page the benchmark marks as evidence.

| Mode | What the model sees | Dev (50) | **Test (100)** | Test grounded | All (150) | All grounded | Refusals (all) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Oracle (ceiling) | The benchmark's evidence page(s) | 98% | 94% | 94% | 95.3% | 95.3% | 0% |
| Closed book | The question only | 80% | 70% | 0% | 73.3% | 0% | 10% |
| BM25, top 5 pages | 5 whole pages, by keyword search | 52% | 43% | 22% | 46.0% | 22.7% | 45% |
| **Routed, top 5 chunks** | 5 chunks, statement-routed | **80%** | **69%** | **60%** | **72.7%** | **60.7%** | 17% |

- **Context:** the routed mode sends the model a median of 2,545 input tokens, about a quarter of BM25's.
- **Cost:** $0.026 per question, answer plus grading.
- **Latency:** median 4.4 s, 90th percentile 8.1 s.
- **Clean key:** leaving out the three questions with contradictory reference answers gives 68.4% on test.

## What this shows

**Grounding nearly triples.** On test, 60% of answers are correct and cite an evidence page, against 22%
for BM25 and 0% for the closed book. Every routed answer cites a page.

**Correctness ties the closed book, but on different questions.** Test correctness is 69% routed against
70% closed book.
- Over all 150 questions, 22 are right only with retrieval and 23 are right only from memory.
- By question type (all 150), routed against closed book:
  - novel-generated (bespoke questions): 68% against 52%;
  - metrics-generated (computed ratios): 86% against 92%;
  - domain-relevant (generic analyst questions about large, well-known companies): 64% against 76%.
- The closed book's score largely reflects memorised public figures for these well-known companies.
  It cannot say where a number came from, and it will not carry over to filings the model has not seen,
  such as the PSX filings planned for phase 2.

**Retrieval is now the bottleneck, not reading.**

| Test questions | Correct | Incorrect | Refused |
| --- | ---: | ---: | ---: |
| Evidence page retrieved (73) | 61 (84%) | 6 | 6 |
| Evidence page not retrieved (27) | 8 | 4 | 15 |

- When the evidence page is retrieved, accuracy is 84%. The oracle, which sees only the evidence pages,
  reaches 94%.
- When it is missed, the model mostly says it cannot answer rather than guessing. 15 of the 27 misses are
  refusals.

## Failure review

All 15 incorrect answers (across all 150) were read. Roughly:
- **Judgement disagrees with the reference (3).** Examples: a quick ratio of 0.96 called "reasonably
  healthy" where the reference says it needs improvement; Pfizer's Upjohn spin-off treated as completed.
- **Incomplete list (4).** Acquisitions, segments, litigation or drivers where the retrieved chunks hold
  only part of the list. These are retrieval misses inside a long section.
- **Wrong figure or calculation (5).** Examples: using consolidated net income instead of net income
  attributable to the parent; applying 10% to $700M instead of solving $700M / 0.9.
- **Committed to a wrong answer while hedging (3).** The answer gives a headline figure and mentions the
  right one only as a caveat or alternative.

## Limits

- **One run each, no variance.** Differences of a few points between modes on 100 questions are within
  noise; the grounding gap (60% against 22%) is not.
- **Grounding is a lower bound.** As in milestone 3, a correct citation to a page that repeats the figure
  but is not the marked page counts as ungrounded.
- **Citing an evidence page is not proof the figure came from it.** A check that the cited page contains
  the reference figure is still open.
- **The filing is given.** Open search across all 84 filings is not yet measured end to end.

## Next

- Raise retrieval recall, chiefly for questions with no statement cue and for list questions that span
  several chunks: wider k for list questions, neighbouring chunks, and query rewriting.
- Measure the open setting.
- Add the cited-page figure check.
