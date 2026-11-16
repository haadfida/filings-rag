"""Download the PSX pilot reports from each company's own website and check that they parse.

Six annual reports, one per company, chosen in DESIGN.md section 8a: each site's terms were read
first, and companies whose terms restrict reuse or whose sites refuse automated clients were left
out. Nothing here touches psx.com.pk. Files go to the git-ignored `data/psx/` and are never
re-hosted. The first download records a SHA-256 for each file in `data/psx/manifest.json`; later
runs skip files that still match, and report a file whose hash changed (a company may replace a
report in place), so a benchmark built on these pages never silently moves.
"""

from __future__ import annotations

import hashlib
import json
import ssl
import time
from dataclasses import dataclass, field
from pathlib import Path

import certifi
import httpx
import pymupdf

from filings_rag.benchmark import DATA_DIR as FINANCEBENCH_DIR
from filings_rag.cachefile import atomic_write_text
from filings_rag.data import _fetch, sha256

PSX_DIR = FINANCEBENCH_DIR.parent / "psx"
USER_AGENT = "filings-rag/0.1 (research benchmark; one download per report)"
PAUSE_SECONDS = 5.0  # between files, and every file comes from a different host anyway

# The two Engro sites send only their own certificate and leave out the issuer's, so a strict client
# cannot reach a trusted root. Browsers fetch the missing issuer from the address the certificate
# names (Authority Information Access); we do the same, pin it by hash, and still require the full
# chain to end at a root in certifi's store. Nothing about verification is relaxed.
SECTIGO_DV_R36 = "http://crt.sectigo.com/SectigoPublicServerAuthenticationCADVR36.crt"
INTERMEDIATES = {SECTIGO_DV_R36: "8c54c334b66ba4e426772af4a3f9136c19a1aec729fdb28c535c07a5a4ef22e0"}


def tls_context(client: httpx.Client) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.verify_flags &= ~ssl.VERIFY_X509_PARTIAL_CHAIN  # an intermediate is never a trust anchor
    for url, digest in INTERMEDIATES.items():
        der = client.get(url).raise_for_status().content
        if hashlib.sha256(der).hexdigest() != digest:
            raise RuntimeError(f"intermediate certificate at {url} does not match its pinned hash")
        ctx.load_verify_locations(cadata=der)
    return ctx


@dataclass(frozen=True)
class Filing:
    ticker: str
    company: str
    year: str  # the report's own label: fiscal year for June year-ends, calendar year otherwise
    url: str

    @property
    def name(self) -> str:
        return f"{self.ticker}_{self.year}_annual"


# Checked by hand on 15-16 Nov 2026 (DESIGN.md 8a). Each URL is the link on the company's own
# investor-relations page.
FILINGS = [
    Filing(
        "MEBL",
        "Meezan Bank",
        "2025",
        "https://www.meezanbank.com/wp-content/themes/mbl/downloads/annualreport2025.pdf",
    ),
    Filing(
        "HUBC",
        "The Hub Power Company",
        "2026",
        "https://hubpower.com/wp-content/uploads/2026/09/HUBCO-Integrated-Annual-Report-2026.pdf",
    ),
    Filing(
        "EFERT",
        "Engro Fertilizers",
        "2025",
        "https://www.engrofertilizers.com/themes/engro/documents/Engro-Fertilizers-Annual-Report-2025.pdf",
    ),
    Filing(
        "SYS",
        "Systems Limited",
        "2025",
        "https://www.systemsltd.com/sites/default/files/2026-04/Systems%20Limited-Annual%20Report%202025.pdf",
    ),
    Filing("DGKC", "D.G. Khan Cement", "2026", "https://www.dgcement.com/financial-reports/DGAnnual2026.pdf"),
    Filing(
        "ENGROH",
        "Engro Holdings",
        "2025",
        "https://www.engro.com/app/media/2026/04/EH-Annual-Report-2025.pdf",
    ),
]


def pdf_path(f: Filing, data_dir: Path = PSX_DIR) -> Path:
    return data_dir / "pdfs" / f"{f.name}.pdf"


@dataclass
class Report:
    downloaded: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def download(data_dir: Path = PSX_DIR, pause: float = PAUSE_SECONDS) -> Report:
    report = Report()
    manifest_path = data_dir / "manifest.json"
    manifest: dict = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    files: dict[str, dict] = manifest.get("files", {})

    def save_manifest() -> None:
        atomic_write_text(manifest_path, json.dumps({"files": files}, indent=2) + "\n")

    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(headers=headers, timeout=30) as plain:
        ctx = tls_context(plain)
    with httpx.Client(headers=headers, timeout=120, follow_redirects=True, verify=ctx) as client:
        first = True
        for f in FILINGS:
            dest = pdf_path(f, data_dir)
            pinned = files.get(f.name, {}).get("sha256")
            if dest.exists() and pinned == sha256(dest):
                report.skipped.append(f.name)
                continue
            if not first:
                time.sleep(pause)
            first = False
            try:
                _fetch(client, f.url, dest)
            except httpx.HTTPError as e:
                report.problems.append(f"{f.name}: download failed ({e})")
                continue
            digest = sha256(dest)
            if pinned and digest != pinned:
                report.problems.append(f"{f.name}: the company's file changed since it was pinned")
            files[f.name] = {
                "url": f.url,
                "sha256": digest,
                "bytes": dest.stat().st_size,
                "downloaded": time.strftime("%Y-%m-%d"),
            }
            save_manifest()
            report.downloaded.append(f.name)
    save_manifest()
    report.problems.extend(p for p in verify(data_dir) if p not in report.problems)
    return report


@dataclass
class Check:
    name: str
    pages: int
    text_pages: int  # pages with a usable text layer
    chars: int

    @property
    def text_share(self) -> float:
        return self.text_pages / self.pages if self.pages else 0.0


MIN_PAGE_CHARS = 200  # fewer extracted characters than this is a picture, a divider or a scan


def check(f: Filing, data_dir: Path = PSX_DIR) -> Check:
    with pymupdf.open(pdf_path(f, data_dir)) as pdf:
        lengths = [len(page.get_text("text").strip()) for page in pdf]
    return Check(f.name, len(lengths), sum(n >= MIN_PAGE_CHARS for n in lengths), sum(lengths))


def verify(data_dir: Path = PSX_DIR) -> list[str]:
    """Problems with the downloaded reports; an empty list means every file is present and readable."""
    problems: list[str] = []
    for f in FILINGS:
        path = pdf_path(f, data_dir)
        if not path.exists():
            problems.append(f"{f.name}: PDF missing")
            continue
        try:
            c = check(f, data_dir)
        except Exception as e:  # a corrupt file must be reported, whatever the parser raises
            problems.append(f"{f.name}: does not open ({e})")
            continue
        if c.text_share < 0.5:
            problems.append(f"{f.name}: only {c.text_pages}/{c.pages} pages have a text layer (scanned?)")
    return problems


def parse(f: Filing, data_dir: Path = PSX_DIR):
    """Parsed pages of a pilot report (cached alongside FinanceBench's, by the report's own name)."""
    from filings_rag.parse import parse_document

    return parse_document(f.name, pdf_path(f, data_dir))


def statement_pages(f: Filing, data_dir: Path = PSX_DIR) -> dict[str, dict[str, list[int]]]:
    from filings_rag.statements import psx_statement_pages

    return psx_statement_pages(parse(f, data_dir))
