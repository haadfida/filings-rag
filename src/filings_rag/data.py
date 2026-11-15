"""Download the FinanceBench open set at a pinned commit and verify it.

Downloads the two metadata files and only the PDFs the 150 questions use, records a SHA-256 for
every file in `data/financebench/manifest.json`, and checks that each PDF opens and is long enough
to contain every evidence page. Re-running skips files whose hash already matches the manifest.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pymupdf

from filings_rag.benchmark import DATA_DIR, DOCUMENTS_FILE, QUESTIONS_FILE, load_questions, pdf_path
from filings_rag.cachefile import atomic_write_text

REPO = "patronus-ai/financebench"
COMMIT = "cc39aeb4afdf33909ee1412188bf89035950c2eb"  # HEAD on 2024-12-03, checked 2026-11-10
RAW = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}"
USER_AGENT = "filings-rag/0.1 (benchmark download)"
EXPECTED_QUESTIONS = 150

# Model answers from the FinanceBench paper, each labelled by a human reviewer. Used to check that our
# grader agrees with people before we trust it (milestone 1). Listed from the repository at COMMIT.
RESULT_FILES = [
    "claude-2_inContext.jsonl",
    "claude-2_inContext_reverse.jsonl",
    "gpt-4-1106-preview_closedBook.jsonl",
    "gpt-4-1106-preview_inContext.jsonl",
    "gpt-4-1106-preview_inContext_reverse.jsonl",
    "gpt-4-1106-preview_oracle.jsonl",
    "gpt-4-1106-preview_oracle_reverse.jsonl",
    "gpt-4-1106-preview_sharedStore.jsonl",
    "gpt-4-1106-preview_singleStore.jsonl",
    "gpt-4_closedBook.jsonl",
    "gpt-4_oracle.jsonl",
    "gpt-4_oracle_reverse.jsonl",
    "gpt-4_sharedStore.jsonl",
    "gpt-4_singleStore.jsonl",
    "llama2_sharedStore.jsonl",
    "llama2_singleStore.jsonl",
]


@dataclass
class Report:
    downloaded: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch(client: httpx.Client, url: str, dest: Path, retries: int = 3) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, retries + 1):
        try:
            with client.stream("GET", url) as r:
                r.raise_for_status()
                with tmp.open("wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
            tmp.replace(dest)
            return
        except httpx.HTTPError:
            tmp.unlink(missing_ok=True)
            if attempt == retries:
                raise
            time.sleep(2 * attempt)


def download(data_dir: Path = DATA_DIR, pause: float = 0.5) -> Report:
    report = Report()
    manifest_path = data_dir / "manifest.json"
    manifest: dict = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    files: dict[str, str] = manifest.get("files", {})

    def save_manifest() -> None:  # after every file, so an interrupted download keeps its progress
        doc = {"source": f"https://github.com/{REPO}", "commit": COMMIT, "files": files}
        atomic_write_text(manifest_path, json.dumps(doc, indent=2) + "\n")

    def get(rel: str) -> None:
        dest = data_dir / rel
        if dest.exists() and files.get(rel) == sha256(dest):
            report.skipped.append(rel)
            return
        source = rel if rel.startswith(("pdfs/", "results/")) else f"data/{rel}"
        _fetch(client, f"{RAW}/{source}", dest)
        files[rel] = sha256(dest)
        save_manifest()
        report.downloaded.append(rel)
        time.sleep(pause)

    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True) as client:
        get(QUESTIONS_FILE)
        get(DOCUMENTS_FILE)
        for name in RESULT_FILES:
            get(f"results/{name}")
        for doc in sorted({q.doc_name for q in load_questions(data_dir)}):
            get(f"pdfs/{doc}.pdf")

    save_manifest()
    report.problems.extend(verify(data_dir))
    return report


def verify(data_dir: Path = DATA_DIR) -> list[str]:
    """Problems with the downloaded data; an empty list means it is complete and consistent."""
    problems: list[str] = []
    questions = load_questions(data_dir)
    if len(questions) != EXPECTED_QUESTIONS:
        problems.append(f"expected {EXPECTED_QUESTIONS} questions, found {len(questions)}")
    if len({q.id for q in questions}) != len(questions):
        problems.append("duplicate question ids")
    missing_results = [n for n in RESULT_FILES if not (data_dir / "results" / n).exists()]
    if missing_results:
        problems.append(f"{len(missing_results)} human-labelled result file(s) missing")

    pages_needed: dict[str, int] = {}
    for q in questions:
        for e in q.evidence:
            pages_needed[e.doc_name] = max(pages_needed.get(e.doc_name, 0), e.page + 1)
        pages_needed.setdefault(q.doc_name, 0)

    for doc, needed in sorted(pages_needed.items()):
        path = pdf_path(doc, data_dir)
        if not path.exists():
            problems.append(f"{doc}: PDF missing")
            continue
        try:
            with pymupdf.open(path) as pdf:
                if pdf.page_count < needed:
                    problems.append(f"{doc}: {pdf.page_count} pages, evidence needs at least {needed}")
        except Exception as e:  # a corrupt file must be reported, whatever the parser raises
            problems.append(f"{doc}: does not open ({e})")
    return problems
