import json
from pathlib import Path

import pytest

from filings_rag.benchmark import (
    CONTRADICTORY_KEYS,
    DATA_DIR,
    QUESTIONS_FILE,
    load_documents,
    load_questions,
    parse_question,
)
from filings_rag.data import verify

RAW = {
    "financebench_id": "financebench_id_03029",
    "company": "3M",
    "doc_name": "3M_2018_10K",
    "question_type": "metrics-generated",
    "question_reasoning": "Information extraction",
    "question": "What is the FY2018 capital expenditure amount (in USD millions) for 3M?",
    "answer": "$1577.00",
    "justification": "",
    "evidence": [
        {
            "evidence_text": "Purchases of PP&E (1,577)",
            "doc_name": "3M_2018_10K",
            "evidence_page_num": 59,
            "evidence_text_full_page": "...",
        }
    ],
}


def test_parse_question_keeps_zero_indexed_page_and_exposes_reader_page():
    q = parse_question(RAW)
    assert q.evidence[0].page == 59
    assert q.evidence[0].page_number == 60
    assert q.justification is None  # empty string normalised
    assert not q.key_is_contradictory


def test_bad_jsonl_line_reports_file_and_line(tmp_path: Path):
    (tmp_path / QUESTIONS_FILE).write_text(json.dumps(RAW) + "\n{not json\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r":2:"):
        load_questions(tmp_path)


def test_verify_reports_missing_pdfs(tmp_path: Path):
    (tmp_path / QUESTIONS_FILE).write_text(json.dumps(RAW) + "\n", encoding="utf-8")
    problems = verify(tmp_path)
    assert "expected 150 questions, found 1" in problems
    assert "3M_2018_10K: PDF missing" in problems


needs_data = pytest.mark.skipif(
    not (DATA_DIR / QUESTIONS_FILE).exists(), reason="run `filings-rag data` first"
)


@pytest.mark.data
@needs_data
def test_downloaded_benchmark_is_complete():
    assert verify() == []


@pytest.mark.data
@needs_data
def test_downloaded_benchmark_matches_the_checked_facts():
    qs = load_questions()
    docs = load_documents()
    assert len(qs) == 150
    assert len({q.doc_name for q in qs}) == 84
    assert len({q.company for q in qs}) == 32
    assert sum(len(q.evidence) for q in qs) == 189
    assert all(q.doc_name in docs for q in qs)
    assert set(CONTRADICTORY_KEYS) <= {q.id for q in qs}


@pytest.mark.data
@needs_data
def test_split_is_50_dev_100_test_and_balanced_by_type():
    from collections import Counter

    from filings_rag.benchmark import split_of

    qs = load_questions()
    assert Counter(split_of(q) for q in qs) == {"dev": 50, "test": 100}
    dev_types = Counter(q.question_type for q in qs if split_of(q) == "dev")
    assert sorted(dev_types.values()) == [16, 17, 17]
