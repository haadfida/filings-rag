"""Grade an answer against the benchmark's reference: correct, incorrect, or refusal.

FinanceBench ships no scorer; the paper's results were graded by people. This judge is checked against
those human grades before its scores are trusted (`filings-rag validate-judge`).
"""

from __future__ import annotations

from filings_rag.benchmark import Question
from filings_rag.llm import LLM, Result

LABELS = ("correct", "incorrect", "refusal")

# Bump when SYSTEM or SCHEMA changes, so grades from different rubrics are never mixed in one run.
# v1: non-answers (pasted text, greetings) graded as refusal.
# v2: non-answers graded as incorrect; refusal only for an explicit decline. Matches the paper's reviewers.
JUDGE_VERSION = "v2"

SYSTEM = """You grade answers to questions about companies' financial filings against a reference answer.

Labels:
- correct: the candidate reaches the same answer as the reference. For numbers, accept different \
formatting, units that are converted correctly (millions vs billions, 0.019 vs 1.9%), and rounding \
differences within the precision the reference uses or about 1% relative, whichever is looser. For \
yes/no or explanatory questions, the candidate's conclusion and the key facts it relies on must agree \
with the reference; extra correct detail is fine.
- incorrect: the candidate gives an answer that disagrees with the reference on the conclusion or on a \
key figure, or answers a different question. Output that does not address the question at all (pasted \
document text, a greeting, unrelated content, or working that stops without a result) is also incorrect.
- refusal: the candidate explicitly declines, saying it cannot answer or that the information it needs \
is missing, and commits to no figure or conclusion. A hedged answer that still commits to one is graded \
correct or incorrect, not refusal.

Grade only against the reference; do not use your own knowledge of the company to overrule it."""

SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {"type": "string", "description": "One or two sentences"},
        "label": {"type": "string", "enum": list(LABELS)},
    },
    "required": ["reason", "label"],
    "additionalProperties": False,
}


def build_prompt(q: Question, candidate: str) -> str:
    justification = f"\nReference working: {q.justification}" if q.justification else ""
    return (
        f"Question: {q.question}\n\nReference answer: {q.answer}{justification}\n\n"
        f"Candidate answer: {candidate}"
    )


def grade(llm: LLM, q: Question, candidate: str, model: str, effort: str) -> Result:
    return llm.json(model=model, system=SYSTEM, user=build_prompt(q, candidate), schema=SCHEMA, effort=effort)
