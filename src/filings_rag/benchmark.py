"""FinanceBench open set: typed records and loaders.

The data is downloaded by `filings_rag.data` into `data/financebench/` and is never committed
(CC BY-NC 4.0, see README). Page numbers in the source are zero-indexed; `Evidence.page` keeps
that, and `Evidence.page_number` gives the one-indexed page a reader would see.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "financebench"
QUESTIONS_FILE = "financebench_open_source.jsonl"
DOCUMENTS_FILE = "financebench_document_information.jsonl"

# Questions whose reference answer contradicts its own worked justification. Found while
# checking the key (see DESIGN.md, section 2). Scores are reported with and without these.
CONTRADICTORY_KEYS: dict[str, str] = {
    "financebench_id_00070": "answer says negative working capital; its own arithmetic gives +124",
    "financebench_id_00438": "answer gives 36.8% and 34.6%; its own fractions give 37.2% and 39.8%",
    "financebench_id_00080": "answer says $1.6bn; the justification sums to about $1.5bn",
}


@dataclass(frozen=True)
class Evidence:
    doc_name: str
    page: int  # zero-indexed, as in the source
    text: str
    full_page_text: str

    @property
    def page_number(self) -> int:
        return self.page + 1


@dataclass(frozen=True)
class Question:
    id: str
    company: str
    doc_name: str
    question_type: str
    reasoning: str | None
    question: str
    answer: str
    justification: str | None
    evidence: tuple[Evidence, ...]

    @property
    def key_is_contradictory(self) -> bool:
        return self.id in CONTRADICTORY_KEYS


@dataclass(frozen=True)
class Document:
    doc_name: str
    company: str
    sector: str
    doc_type: str
    period: int
    link: str


def _read_jsonl(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(f"{path}:{line_no}: {e}") from e


def _evidence(raw: dict, default_doc: str) -> Evidence:
    return Evidence(
        doc_name=raw.get("doc_name") or raw.get("evidence_doc_name") or default_doc,
        page=int(raw["evidence_page_num"]),
        text=raw["evidence_text"],
        full_page_text=raw.get("evidence_text_full_page") or "",
    )


def parse_question(raw: dict) -> Question:
    return Question(
        id=raw["financebench_id"],
        company=raw["company"],
        doc_name=raw["doc_name"],
        question_type=raw["question_type"],
        reasoning=raw.get("question_reasoning"),
        question=raw["question"],
        answer=raw["answer"],
        justification=raw.get("justification") or None,
        evidence=tuple(_evidence(e, raw["doc_name"]) for e in raw["evidence"]),
    )


def parse_document(raw: dict) -> Document:
    return Document(
        doc_name=raw["doc_name"],
        company=raw["company"],
        sector=raw["gics_sector"],
        doc_type=raw["doc_type"],
        period=int(raw["doc_period"]),
        link=raw["doc_link"],
    )


def load_questions(data_dir: Path = DATA_DIR) -> list[Question]:
    return [parse_question(r) for r in _read_jsonl(data_dir / QUESTIONS_FILE)]


def load_documents(data_dir: Path = DATA_DIR) -> dict[str, Document]:
    return {d.doc_name: d for d in (parse_document(r) for r in _read_jsonl(data_dir / DOCUMENTS_FILE))}


def pdf_path(doc_name: str, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / "pdfs" / f"{doc_name}.pdf"


# Human labels in the paper's result files, mapped to our three grades.
HUMAN_LABELS = {"Correct Answer": "correct", "Incorrect Answer": "incorrect", "Refusal": "refusal"}


@dataclass(frozen=True)
class LabelledAnswer:
    """A model answer from the FinanceBench paper with the grade a human reviewer gave it."""

    question_id: str
    source: str  # result file stem, e.g. "gpt-4_oracle"
    model_answer: str
    label: str  # correct | incorrect | refusal


def load_labelled_answers(data_dir: Path = DATA_DIR) -> list[LabelledAnswer]:
    out: list[LabelledAnswer] = []
    for path in sorted((data_dir / "results").glob("*.jsonl")):
        for raw in _read_jsonl(path):
            label = HUMAN_LABELS.get(raw.get("label", ""))
            if label is None or raw.get("model_answer") is None:
                continue
            out.append(LabelledAnswer(raw["financebench_id"], path.stem, str(raw["model_answer"]), label))
    return out


def split_of(question: Question) -> str:
    """Fixed dev/test split: "dev" or "test". Tune only on dev; the test score is the headline.

    Within each question type, questions are ordered by a hash of their id and the first third go to
    dev, giving 50 dev and 100 test questions. Hash order is stable across machines and runs.
    """
    return _SPLIT[question.id]


def _build_split(questions: list[Question]) -> dict[str, str]:
    import hashlib

    split: dict[str, str] = {}
    by_type: dict[str, list[Question]] = {}
    for q in questions:
        by_type.setdefault(q.question_type, []).append(q)
    # One third of all questions go to dev; the remainder of the division goes to the types in name order.
    total_dev = round(len(questions) / 3)
    types = sorted(by_type)
    quota = {t: len(by_type[t]) // 3 for t in types}
    for t in types[: total_dev - sum(quota.values())]:
        quota[t] += 1
    for t in types:
        group = sorted(by_type[t], key=lambda q: hashlib.sha256(q.id.encode()).hexdigest())
        n_dev = quota[t]
        for i, q in enumerate(group):
            split[q.id] = "dev" if i < n_dev else "test"
    return split


class _LazySplit(dict):
    def __missing__(self, key: str) -> str:
        if not self:
            self.update(_build_split(load_questions()))
            return self[key]
        raise KeyError(key)


_SPLIT: dict[str, str] = _LazySplit()
