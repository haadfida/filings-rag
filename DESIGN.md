# Filings RAG: design

Status: this is the plan as written before building, on 10 Nov 2026; facts below say how each was checked.
Milestones 0 to 5 are now done. What was built, and where it departed from this plan, is in the
[README](README.md) and the [results](results/) write-ups; section 8 records the decisions made.

## 1. Goal

One Python engine that answers questions about a company from its own filings and cites the page for every figure.

- **Phase 1, FinanceBench:** a comparable score on a public benchmark over US filings.
- **Phase 1b, public MCP server:** the retrieval half of the engine as a free MCP server over live SEC filings, so any agent (Claude Code, Cursor and others) can search a company's filings and get passages with citations. See section 3a.
- **Phase 2, PSX:** the same engine on Pakistan Stock Exchange filings, as a live demo with real users.

What the project has to prove, in order: retrieval over long, messy PDFs; honest measurement; cost and latency awareness; a record of failures and fixes.

## 2. What the checks found

### FinanceBench (read from the repository, commit `cc39aeb`)

| Question | Finding |
| --- | --- |
| Licence | No licence file in the GitHub repository. The Hugging Face copy (`PatronusAI/financebench`) is tagged `cc-by-nc-4.0`. Noncommercial use with attribution is allowed. |
| Size | 150 questions, 84 filings, 32 companies. 112 questions are on annual reports (10-K), 15 on 10-Q, 14 on earnings releases, 9 on 8-K. |
| Types | 50 metrics-generated, 50 domain-relevant, 50 novel-generated. |
| Evidence | Every question has evidence text and a page number (zero-indexed), 189 evidence items in total. |
| Scoring | No scorer in the repository. The paper's results were graded by hand (2,400 labelled answers in `results/*.jsonl`). |
| Answer format | 98 of 150 answers are free text. Number formats and rounding are inconsistent. |

**Answer-key problems.** A third-party audit claimed 10% of the key has hundredfold unit errors. That is mostly wrong: the 15 percentage answers are consistent inside the question file ("1.9%") and differ only from a second results file (0.019). Three real conflicts were found, where the answer contradicts its own justification:

| Id | Problem |
| --- | --- |
| `financebench_id_00070` | Answer says working capital is negative (-$1,561M); its own arithmetic gives +124, and the results file says positive. |
| `financebench_id_00438` | Answer gives margins of 36.8% and 34.6%; the justification's fractions give 37.2% and 39.8%. |
| `financebench_id_00080` | Answer says $1.6bn; the justification sums to about $1.5bn. |

Not checked: the 50 metrics-generated answers were not recomputed from the PDFs.

### PSX filings (30 polite requests, 5 PDFs sampled)

| Question | Finding |
| --- | --- |
| Can reports be listed? | Yes. `financials.psx.com.pk` returns a JSON list per symbol, back to 2013. About 1,020 PDFs for 23 large companies. |
| Is the listing current? | No. The newest entry is dated 30 Apr 2026. Cause unknown. |
| Do they parse? | Recent reports: 78–96% of pages have a text layer. A 2013 report: half the pages are scans. |
| Tables | Numbers extract exactly. PyMuPDF's `find_tables()` mangles labels; rebuilding rows from word coordinates works. |
| Other snags | Units vary ('000, millions, full rupees) even inside one document; consolidated and unconsolidated statements share a file; Urdu pages extract with reversed letters. |
| **Terms of use** | **The PSX data portal's terms forbid automated tools and building collections from its content without written permission.** The reports are also each company's copyright. |

Verdict: technically practical, legally not as a bulk crawl of the PSX portal. See open question 7.

### Second benchmark

| Benchmark | Size | Why | Licence |
| --- | --- | --- | --- |
| Fin-RATE | 7,500 questions, three task types, US filings | Cross-company and multi-year questions; top systems score about 43–44% | MIT (Hugging Face card) |
| T²-RAGBench | 23,088 text-and-table questions | Large enough to measure retrieval precisely | Not found |

Recommendation: add a 150-question sample of Fin-RATE later, as the stretch target. Skip T²-RAGBench.

## 3. Architecture

```
PDFs ──> parse ──> chunk ──> index (BM25 + vectors)
                                   │
question ──> retrieve ──> rerank ──> answer with page citations ──> grade
                 │            │              │                       │
                 └────────────┴── trace: timings, tokens, cost ──────┘
```

| Stage | What it does | Notes |
| --- | --- | --- |
| Ingest | Download filings at build time, record source URL and hash | Never re-host benchmark PDFs or questions |
| Parse | PyMuPDF text per page; rebuild table rows from word coordinates; flag pages with no text layer | Keep page numbers on everything; log parse failures |
| Chunk | Prose by section and paragraph; each financial statement table as one chunk with its header and units line | Tables are where most numeric questions fail |
| Index | BM25 plus a dense embedding index, merged by reciprocal rank | Financial terms and exact numbers favour BM25; paraphrased questions favour vectors |
| Retrieve | Filter to the named company and filing first, then hybrid search | FinanceBench names the document, so both "known document" and "find the document" settings are measurable |
| Answer | Claude with the retrieved chunks; every figure must cite a page; must say "not found" when evidence is missing | Refusal is scored separately from a wrong answer |
| Grade | Section 5 | |
| Trace | One JSON line per question: retrieved pages, timings, tokens, cost, model, prompt version | Enough for a failures page and a cost table |

## 3a. Public MCP server

The retrieval engine, packaged so other people's agents can use it. This is the "real users" evidence for phase 1, before PSX.

**Principle: the server retrieves, the caller's model reasons.** The server makes no Claude calls. It returns passages with citations and the user's own agent writes the answer. So it costs nothing per query to run, needs no API key from anyone, and holds no secrets.

| Tool | Input | Returns |
| --- | --- | --- |
| `find_filings` | ticker or company name, form type (10-K, 10-Q, 8-K), year range | Filing list: accession number, form, period, filing date, EDGAR URL |
| `search_filing` | accession number, question, `k` | Top passages and tables with section, page where known, and a link to the source |
| `get_page` | accession number, page or section | The full text of that page or section, for checking a passage in context |

All three are read-only.

**Data source: SEC EDGAR, fetched live.** US filings on EDGAR are public records, so a commercial listing later is not blocked by the data. The FinanceBench files are never bundled: they are licensed for noncommercial use only.

- EDGAR's fair-access rules ask for at most 10 requests a second and a `User-Agent` that names the operator with a contact address (open question 9).
- Downloaded filings are cached locally, keyed by accession number.
- Filings are indexed on first use, so the first question about a filing is slow and later ones are fast.

**The page-number problem.** Most EDGAR filings are HTML, not PDF, so "page" is not built in.

- Page breaks in the HTML and the printed page numbers in footers recover pages for most 10-Ks.
- Where they are missing, cite the section ("Item 7", "Note 12") and an anchor link instead.
- Measure how often each case happens.

**Packaging and listing.**

- Python package using the official MCP Python SDK, run locally over stdio (`uvx filings-rag-mcp`).
- Optionally, a hosted Streamable HTTP endpoint later.
- Code under the MIT licence.
- Listed free on the official MCP registry.
- Paid marketplaces are a later, separate decision (open question 10).

**How it is measured.** 112 of the 150 FinanceBench questions are about 10-K reports, which also exist on EDGAR.

- Map each of those filings to its EDGAR accession number.
- Report the evidence-page hit rate through the MCP tools next to the hit rate on the original PDFs.
- If the hit rate drops on EDGAR's HTML, the gap is published, not hidden.

## 4. Stack

| Choice | Reason |
| --- | --- |
| Python 3.12, `uv`, `pytest`, `ruff` | Standard for AI roles; fast setup |
| PyMuPDF | Already tested on the sample filings; exact numbers, word coordinates available |
| `bm25s` or `rank_bm25` | Simple, local, no service |
| Local open-source embedding model via `sentence-transformers` | Free, no second API key, reproducible |
| LanceDB (file-based) for phase 1 | No server to run; swap to Postgres with pgvector for the live demo |
| `anthropic` Python SDK | Official SDK; streaming, prompt caching, batches |
| FastAPI | Thin API for the demo; common in job descriptions |
| React + Vite front end | Reuses the AssetPilot pattern, including bring-your-own-key |

Models (ids and prices from the Claude API reference, cached 3 Nov 2026):

| Role | Model | Input / output per 1M tokens |
| --- | --- | --- |
| Main answerer | `claude-opus-5-5` | $4.00 / $20.00 |
| Mid comparison | `claude-sonnet-5-5` | $2.00 / $10.00 |
| Small comparison | `claude-haiku-5-5` | $0.10 / $0.50 |
| Judge for free-text answers | `claude-opus-5-5` | $4.00 / $20.00 |

API notes that affect the design: Opus 5.5 always thinks, so effort is the cost control and must be set explicitly (its default is `medium`); sampling parameters such as temperature are rejected, so variance is measured by repeat runs; Message Batches run at half price and suit eval runs; the API's citations feature returns page locations but cannot be combined with structured outputs.

## 5. Evaluation method

1. **Split.** 50 development questions and 100 held-out test questions, stratified by question type. Tune only on development. The test score is the headline.
2. **Retrieval.** Because every question has an evidence page: hit rate at k (is the evidence page in the top k) and rank of the first hit. Reported for "document given" and "document not given".
3. **Answers.** Three labels, as in the paper: correct, incorrect, refused.
   - Numeric answers: a deterministic checker that normalises units, percent signs and rounding.
   - Free-text answers: an LLM judge with the reference answer and evidence.
4. **Validate the judge first.** The repository ships 2,400 model answers with human labels. Run the judge on a sample of those and report its agreement with the humans before trusting it on our answers.
5. **Baselines.** Closed book (no documents), oracle (the evidence page handed over), and plain BM25. The oracle score is the ceiling for retrieval work.
6. **Variance.** Three runs of the final configuration; report mean and range.
7. **Key problems.** Report scores with and without the three contradictory questions, and publish the finding.
8. **Model comparison.** Same pipeline on the three models: accuracy, cost per question, median latency.
9. **Failure log.** Each failed test question classified as parse, retrieval, reasoning, or key error.

## 6. Milestones

Sized for evenings; about three weeks.

| # | Milestone | Done when |
| --- | --- | --- |
| 0 | Repository, data download script, licence note | `make data` fetches the 150 questions and 84 PDFs |
| 1 | Baselines: closed book, oracle, judge validated against human labels | Three numbers and a judge-agreement figure |
| 2 | Parser and chunker with table handling | Evidence text found in the parsed page for at least 95% of evidence items |
| 3 | Hybrid retrieval | Hit-rate table on the development set |
| 4 | Answering with citations and refusal | First end-to-end development score |
| 5 | Iterate on failures | Failure log; development score stops improving |
| 6 | Test run, three repeats, model comparison | Headline table |
| 7 | Tracing, cost table, demo UI with bring-your-own-key | Hosted demo |
| 7a | MCP server over live EDGAR (section 3a) | Installs with one command; hit rate on the 112 10-K questions reported next to the PDF hit rate |
| 7b | Registry listing and install guide | Listed on the official MCP registry; usage counted without collecting questions |
| 8 | Write-up: README, failures page, portfolio card | Published |
| 9 | PSX pilot (after open question 7 is settled) | 10 companies, 50 hand-checked questions |
| 10 | Stretch: Fin-RATE sample | Score on 150 multi-document questions |

## 7. Budget

Measured: about $28 of model calls through milestone 5 (see each results page). The original estimates follow.
Estimates, written before milestone 1. Assumes about 10,000 input and 1,500 output tokens per question.

| Run | Estimated cost |
| --- | --- |
| 150 questions on `claude-haiku-5-5` | about $0.30 |
| 150 questions on `claude-sonnet-5-5` | about $5 |
| 150 questions on `claude-opus-5-5` | about $10 |
| Judge pass on 150 answers | about $2 |

Ten full Opus runs would use the whole $100, so: iterate on the 50-question development set with Haiku or Sonnet, keep full Opus runs to about four, use Message Batches (half price) for full runs, and cache the system prompt. Parsing uses no model calls.

## 8. Decisions

How the open questions in the original plan were settled.

1. **Vector store.** None yet: 65,423 chunks fit in a NumPy matrix cached per filing. A vector database
   is for the hosted demo.
2. **Table chunking.** Each table is one chunk with its caption, units line and column years (milestone 2).
3. **Citations.** The model cites `[p. N]` inside structured output, and grounding is checked against
   the benchmark's evidence pages.
4. **Document setting.** "Document given" is reported. Open search across all filings is built but not
   yet reported.
5. **Agent step.** Single retrieve-then-answer so far.
6. **Embedding model.** A small general model (`BAAI/bge-small-en-v1.5`) run locally; statement routing
   and query rewriting mattered more than the embedding (milestones 3 and 5).
7. **PSX source.** Open. No automated collection from the PSX portal without written permission.
8. **EDGAR contact.** The MCP server will send a dedicated project contact in its `User-Agent`, as the
   SEC asks.

## 8a. PSX pilot: sources and terms (checked 15–16 Nov 2026)

The PSX data portal's terms require written permission for automated access and compilations. A
request went to PSX's Market Data Team on 15 Nov 2026; until it is answered, nothing is fetched from any
psx.com.pk site. The pilot instead takes each company's reports from the company's own investor-relations
site, the way FinanceBench takes US filings from their source: downloaded at build time, hashed, never
re-hosted. Only questions, short quotations, page references and links back are published.

Each candidate site's terms were read (two were re-checked by hand). Pilot set, the latest annual report
of each:

| Company (ticker) | Sector | Report | Terms found |
| --- | --- | --- | --- |
| Meezan Bank (MEBL) | Islamic bank | [Annual Report 2025](https://www.meezanbank.com/wp-content/themes/mbl/downloads/annualreport2025.pdf), 24 MB | Disclaimer covers privacy and warranties only |
| Hub Power (HUBC) | Power | [Integrated Annual Report 2026](https://hubpower.com/wp-content/uploads/2026/09/HUBCO-Integrated-Annual-Report-2026.pdf), 16 MB | No terms page |
| Engro Fertilizers (EFERT) | Fertiliser | [Annual Report 2025](https://www.engrofertilizers.com/themes/engro/documents/Engro-Fertilizers-Annual-Report-2025.pdf) | Warranty-only disclaimer |
| Systems Limited (SYS) | Technology | [Annual Report 2025](https://www.systemsltd.com/sites/default/files/2026-04/Systems%20Limited-Annual%20Report%202025.pdf), 16 MB | Terms page holds a privacy policy only |
| D.G. Khan Cement (DGKC) | Cement | [Annual Report 2026](https://www.dgcement.com/financial-reports/DGAnnual2026.pdf), 10 MB | No terms page |
| Engro Holdings | Conglomerate | [Annual Report 2025](https://www.engro.com/app/media/2026/04/EH-Annual-Report-2025.pdf), 43 MB | Warranty-only disclaimer |

Excluded, and why:
- **HBL, UBL:** terms forbid copying or downloading beyond personal use without written consent.
- **PSO:** extracts are allowed for non-commercial use, but not "incorporated in any other work,
  publication, or site", which a published benchmark would be.
- **Nestlé Pakistan:** terms forbid deep linking, and our manifest links to the PDFs.
- **Lucky Cement:** terms forbid extracting content by automated means.
- **OGDC, PPL, Mari, FFC, MCB, Fauji Cement:** the sites refuse automated clients (HTTP 403); terms not
  verified. Candidates only if a company grants permission, which would also fill the missing
  exploration-and-production sector.

The silence of a terms page is not a licence: the reports remain each company's copyright. The pilot
relies on the same practice as the US phase (research use, no re-hosting, short attributed quotations),
and any company that objects is removed.

### Download and parse check (16 Nov 2026)

`filings-rag psx-data` downloads the six reports from the company sites, five seconds apart, into the
git-ignored `data/psx/`, and pins each file's SHA-256 in `data/psx/manifest.json`. Both Engro sites leave
the issuing certificate out of their TLS chain. The downloader fetches it from the address in the site
certificate, as browsers do, pins it by hash, and still requires the chain to end at a trusted root.

- **Engro Fertilizers is unreadable without OCR.** 213 of its 249 pages have no text layer, and the
  pages sampled had their text converted to vector outlines (thousands of shapes, no fonts). It stays in the list but out of the benchmark until
  OCR is added. The other five have a text layer on 87–91% of pages.
- **Tables parse as they are.** Rows, note columns and bracketed negatives come through unchanged.
- **Statement finding needs its own rules.** Each report holds two full sets, unconsolidated (the
  company's own) and consolidated (the group's). Titles differ from US filings ("Statement of Profit or
  Loss", "Profit and Loss Account") and are often split over two lines. One report prints two statements
  side by side on a page. The analysis section repeats the exact titles over six-year summaries and
  vertical analyses.

  `psx_statement_pages` (statements.py, `psx-v1`) handles these:
  - A title must fill a whole line, cell or pair of lines.
  - Look-alike sections are excluded.
  - Pages are returned per basis.
  - A continuation page must repeat the statement's date line.

  It finds all three statements on both bases in all five reports (30 picks, each checked by hand
  against the page heading). Questions will name their basis.
- **Units.** Rupee forms ("Rupees in '000", "(Rs. '000s)", "Rs. (Millions)", "(Amounts in thousand)", a
  "Rupees" column header) are now recognised. They are tried only after the US rule, so FinanceBench is
  unchanged: statement picks are identical for all 84 filings and units for all 12,013 pages.

## 9. Risks

- **Overfitting 150 questions.** Mitigated by the held-out split and by reporting development and test separately.
- **Judge error.** Mitigated by validating against the human labels.
- **A crowded top end.** One 2026 paper self-reports 89.3%. The score alone will not stand out; the judge validation, the key audit and the failure log are what will.
- **PSX legal exposure.** See open question 7.
- **Budget.** See section 7.
- **EDGAR access.** Rate limits or blocking if the server is used heavily. Mitigated by the local cache and by staying under 10 requests a second.
- **HTML page numbers.** Citations may be section-level for some filings. Measured and published, as in section 3a.

## Sources

- FinanceBench repository: https://github.com/patronus-ai/financebench
- FinanceBench on Hugging Face: https://huggingface.co/datasets/PatronusAI/financebench
- FinanceBench paper: https://arxiv.org/abs/2311.11944
- Fin-RATE: https://huggingface.co/datasets/GGLabYale/Fin-RATE and https://arxiv.org/abs/2602.07294
- T²-RAGBench: https://t2ragbench.demo.hcds.uni-hamburg.de/
- MimirRAG (89.3% self-reported): https://arxiv.org/html/2605.25030v1
- Answer-key audit: https://gov.tesseract.academy/research/financial-answer-verification
- SEC EDGAR fair access (10 requests a second, declared User-Agent): https://www.sec.gov/os/accessing-edgar-data
- MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
- Official MCP registry: https://registry.modelcontextprotocol.io
