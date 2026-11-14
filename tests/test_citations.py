import pytest

from filings_rag.benchmark import parse_question
from filings_rag.citations import cited_pages, cites_evidence
from tests.test_benchmark import RAW


@pytest.mark.parametrize(
    ("text", "pages"),
    [
        ("Capex was $1,577M [p. 49].", {49}),
        ("See [p. 49, p. 50] and [p. 7; p. 9].", {49, 50, 7, 9}),
        ("Revenue grew [pp. 49-51].", {49, 50, 51}),
        ("Revenue grew [p. 12–13].", {12, 13}),
        ("Listed [p. 4, 5, 6] and [pp. 8, 9].", {4, 5, 6, 8, 9}),
        ("[p. 3; Exhibit 10.1, p. 5]", {3, 5}),
        ("FY2022 [FY2022] and a formula [(1,577 + 2) / 3]", set()),
        ("No brackets: page 4", set()),
        (None, set()),
    ],
)
def test_cited_pages(text, pages):
    assert cited_pages(text) == pages


def test_cites_evidence_uses_one_indexed_pages():
    q = parse_question(RAW)  # evidence page 59, zero-indexed
    assert cites_evidence(q, "Capex was $1,577M [p. 60].")
    assert not cites_evidence(q, "Capex was $1,577M [p. 59].")
    assert not cites_evidence(q, "Capex was $1,577M.")
