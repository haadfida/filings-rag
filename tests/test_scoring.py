"""The code behind the headline numbers, on synthetic data (no benchmark download needed)."""

import json
from dataclasses import replace

from filings_rag import rewrite
from filings_rag.benchmark import _build_split, parse_question
from filings_rag.retrieval_eval import _score
from filings_rag.runner import _read, _scores, mcnemar_p
from tests.test_benchmark import RAW

Q = parse_question(RAW)  # evidence on zero-indexed page 59, which answers cite as [p. 60]


def _q(i: int, qtype: str = "metrics-generated"):
    return replace(Q, id=f"q{i:03d}", question_type=qtype)


def test_read_keeps_the_last_row_per_key(tmp_path):
    path = tmp_path / "grades.jsonl"
    rows = [{"key": "a", "error": "HTTP 400"}, {"key": "b", "label": "correct"}]
    rows.append({"key": "a", "label": "refusal"})
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    assert _read(path) == {"a": rows[2], "b": rows[1]}


def test_scores_grounded_needs_correct_and_an_evidence_page():
    qs = [_q(1), _q(2), _q(3), _q(4)]
    answers = {
        "q001": {"answer": "$1,577 million [p. 60]"},  # correct, cites evidence page
        "q002": {"answer": "$1,577 million [p. 59]"},  # correct, wrong page (one-indexed 59 is index 58)
        "q003": {"answer": "$1,373 million [p. 60]"},  # incorrect
        "q004": {"answer": "Cannot answer."},
    }
    grades = {
        "q001": {"label": "correct"},
        "q002": {"label": "correct"},
        "q003": {"label": "incorrect"},
        "q004": {"label": "refusal"},
    }
    s = _scores(qs, answers, grades)
    assert s == {
        "n": 4,
        "ungraded": 0,
        "correct": 0.5,
        "grounded": 0.25,
        "incorrect": 0.25,
        "refusal": 0.25,
        "cites_a_page": 0.75,
    }


def test_scores_report_ungraded_instead_of_hiding_them():
    qs = [_q(1), _q(2)]
    s = _scores(qs, {"q001": {"answer": "x"}, "q002": {"answer": "y"}}, {"q001": {"label": "correct"}})
    assert s["n"] == 1 and s["ungraded"] == 1


def test_hit_at_k_and_mrr():
    ranked = [[("d", 1), ("d", 2)], [("d", 5), ("d", 9)], [("d", 7)]]
    gold = [{("d", 1)}, {("d", 9)}, {("d", 3)}]
    s = _score(ranked, gold, [100, 200, 300])
    assert s["hit@1"] == round(1 / 3, 3) and s["hit@3"] == round(2 / 3, 3)
    assert s["mrr@10"] == round((1 + 0.5 + 0) / 3, 3)
    assert s["context_chars_top5"] == 200


def test_split_is_stratified_50_100():
    qs = [_q(i, t) for t in ("metrics-generated", "domain-relevant", "novel-generated") for i in range(50)]
    qs = [replace(q, id=f"{q.question_type}-{q.id}") for q in qs]
    split = _build_split(qs)
    assert sum(v == "dev" for v in split.values()) == 50
    for t in ("metrics-generated", "domain-relevant", "novel-generated"):
        assert sum(split[q.id] == "dev" for q in qs if q.question_type == t) in (16, 17)


def test_mcnemar_exact():
    assert mcnemar_p(0, 0) == 1.0
    assert round(mcnemar_p(14, 5), 3) == 0.064
    assert mcnemar_p(41, 6) < 0.001


def test_rewrite_prompt_is_versioned():
    # If this fails, the rewrite model or prompt changed: bump REWRITE_VERSION and regenerate rewrites.
    assert (rewrite.REWRITE_VERSION, rewrite.PROMPT_FINGERPRINT) == ("v1", "339aeeae0663")
    assert rewrite.SHIPPED_FILE.exists()
