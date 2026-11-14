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
