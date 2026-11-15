# Milestone 5: raising retrieval recall

Run on 15 Nov 2026. Retrieval changes were designed on the 50 dev questions; the 100 test questions were
scored once at the end. Answers from `claude-opus-5-5` at effort `medium`, graded by `claude-opus-5-5` with
judge rubric v2, as in milestone 4. Cost: $3.93 for answering and grading, plus $0.0125 for query rewrites
of all 150 questions.

## Changes

1. **Correct statement pages.** Milestone 3's router chose, for each statement, the titled page with the
   most table rows. That often picked a look-alike: a reclassification table, a parent-company note, a
   guarantor schedule or a subsidiary's statements filed as an exhibit. The new rule
   (`src/filings_rag/statements.py`):
   - the title must be a short line of its own;
   - look-alikes are skipped (consolidating, guarantor, parent company, segment, supplemental);
   - index pages that list several statement titles are skipped;
   - the primary statements sit together, so it takes the earliest set of the three spanning at most 8
     pages.
   This changed the chosen page for 36 statement/filing pairs; every one spot-checked is the real primary
   statement.
2. **A "PPNE" cue** for property, plant and equipment.
3. **Query rewriting** (`src/filings_rag/rewrite.py`). `claude-haiku-5-5` turns each question into three
   searches in the filing's own wording ("capex" becomes "purchases of property, plant and equipment").
   - The question and each rewrite are searched and re-ranked separately, then fused by reciprocal rank.
   - Rewrites are cached; all 150 cost $0.0125.
4. **One chunk per page** after the routed statement chunks, so the top 5 covers more pages.

Tried and dropped (dev): dense search instead of re-ranking as the fallback (hit@5 68% against 80%); scoring
the union of all rewrites' candidates by the question (same as fusion, no better); taking each candidate's
best score over the rewrites (hit@1 fell to 54%).

## Retrieval (filing given)

| Method | Dev hit@5 | Test hit@1 | **Test hit@5** | Test hit@10 | Test MRR@10 | Context (top 5) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Milestone 3: routing + re-ranking | 74% | 52% | 73% | 75% | 0.60 | 4,781 |
| + correct statement pages, PPNE cue | 80% | 60% | 79% | 81% | 0.68 | 4,746 |
| **+ query rewrites, one chunk per page** | **88%** | **61%** | **89%** | **95%** | **0.73** | 5,043 |

Test matches dev (89% against 88%), so the tuning did not overfit the dev set.

## Answers

| Mode | Dev | **Test** | Test grounded | All (150) | All grounded | Refusals (all) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Oracle (ceiling) | 98% | 94% | 94% | 95.3% | 95.3% | 0% |
| Closed book | 80% | 70% | 0% | 73.3% | 0% | 10% |
| BM25, top 5 pages | 52% | 43% | 22% | 46.0% | 22.7% | 45% |
| Milestone 4: routed | 80% | 69% | 60% | 72.7% | 60.7% | 17% |
| **Milestone 5: routed + rewrites** | **86%** | **78%** | **68%** | **80.7%** | **69.3%** | 8% |

- **Clean key:** leaving out the three contradictory reference answers gives 77.6% on test.
- **Context:** median 2,728 input tokens per question.
- **Cost:** $0.026 per question, answer plus grading.
- **Latency:** median 4.7 s.

**Retrieval now beats memory.** Test correctness is 78% against the closed book's 70%. Over all 150, 22
questions are right only with retrieval and 11 only from memory (milestone 4: 22 and 23).

**Reading is now the bottleneck, not retrieval.** On test:

| Test questions | Correct | Incorrect | Refused |
| --- | ---: | ---: | ---: |
| Evidence page retrieved (89) | 71 (80%) | 11 | 7 |
| Evidence page not retrieved (11) | 7 | 2 | 2 |

The oracle reaches 94% from the evidence pages alone, so the 14-point gap on retrieved questions comes
from the extra chunks distracting the model, from a table chunk holding only part of a page, or from
reasoning and definition choices.

## Failure review

All 17 incorrect answers (across all 150) were read. Roughly:
- **Definition or judgement differs from the reference (6).** Examples: a narrower quick-ratio definition
  (0.85 against 0.96); calling a 0.54 quick ratio acceptable for Verizon; treating Pfizer's Upjohn spin-off
  as completed; common book value per share against the reference's figure.
- **Incomplete list or drivers (4).** Acquisitions, regions or margin drivers where only part was found.
- **Wrong figure or calculation (4).** Consolidated against attributable net income; $700M / 0.9;
  rounding outside the reference's precision; a store count from the wrong line.
- **Committed to the wrong headline (3).** The right answer appears only as a caveat or alternative.

## Limits

- **One run each, no variance.** On 100 questions a few points is within noise; the gains here (69% to
  78% correct, 73% to 89% hit@5) are larger than that, but a repeat run would firm them up.
- **Grounding is a lower bound,** and citing an evidence page does not prove the figure came from it (the
  cited-page figure check is still open).
- **The filing is given.** Open search across all 84 filings is not yet measured.
- **Rewriting adds a model call** to every question (Haiku, about $0.0001 and well under a second).

## Next

- Close the reading gap: give the model the whole page for routed statement chunks, and prompt it to
  state the definition it uses for ratios.
- Measure the open setting, then build the MCP server.
