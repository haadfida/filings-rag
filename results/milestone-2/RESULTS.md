# Milestone 2: table-aware parsing and chunking

Run on 15 Nov 2026 over the 84 filings the benchmark uses. No model calls; cost $0. Reproduce with
`filings-rag parse-eval` (about two minutes the first time, then cached).

## What changed

PyMuPDF's plain text writes each table cell on its own line, so a row label and its numbers end up
several lines apart:

```
Depreciation and amortization


1,488

1,544
```

The new parser (`src/filings_rag/parse.py`) groups words into visual rows by their vertical position and
turns wide horizontal gaps into column breaks:

```
(Millions) | 2018 | 2017 | 2016
Depreciation and amortization | 1,488 | 1,544 | 1,474
```

It also reads the units the page states ("in millions", "(In thousands, except per share)").

The chunker (`src/filings_rag/chunk.py`) then cuts each page into chunks:

- **Table chunks** are whole tables, each with its caption, a units line and the page's column years, so
  a retrieved row is never separated from what its numbers mean.
- **Prose chunks** are about 1,200 characters, split at line boundaries.
- Every chunk keeps its page number, so citations still resolve to pages.

## Results

| Measure | Plain text | New parser |
| --- | ---: | ---: |
| Evidence passages recovered (90%+ of their text on the marked page) | 185 / 189 (97.9%) | 181 / 189 (95.8%) |
| Named line items whose label and numbers share one line | **0 / 90** | **90 / 90** |
| ...and whose chunk also carries the units and column years | – | 90 / 90 |

The milestone's target was 95% evidence recovery; the parser meets it.

**How the measures work**
- **Evidence recovery** compares character 8-grams with whitespace and our column separators removed.
  Whitespace has to be ignored because the benchmark's own evidence text glues words together on some
  filings (`consolidatedbalancesheets`).
- **Row integrity** uses ground truth already in the benchmark: the 50 metrics questions name the exact
  line items they used ("a single line item named: Total net sales"), 92 labels in all. 90 of them
  appear on the evidence page; two do not, under any parser.

**The trade-off**
- The new parser recovers four fewer evidence passages, because it reorders some multi-line column
  headers.
- In exchange, every line item a metrics question depends on can now be read as a row.
- For retrieval that is the better trade: keyword and vector search can only match "Total net sales"
  to "$34,229" if they are in the same chunk, and preferably on the same line.

## Chunk statistics

65,423 chunks across the 84 filings: 19,030 table chunks and 46,393 prose chunks.

## Limits

- **Units come from the top of the page.** A page that mixes units, such as millions in a statement and
  billions in a summary, gets the first one.
- **No OCR.** Scanned pages would yield nothing; none of the benchmark's evidence pages are scanned.
- **Tuned by hand** on statements from 3M, Pfizer and Block. Banks' multi-level column headers are only
  partly handled: header rows are kept, but not merged into one header.

## Next

Milestone 3 runs retrieval over these chunks (BM25 plus vectors). It is measured by whether an evidence
page comes back in the top results on the dev split; the page-level BM25 baseline managed 13 of 50.
