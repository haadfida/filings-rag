"""The PSX pilot list: company websites only, never the exchange's data portal (DESIGN.md 8a)."""

from urllib.parse import urlparse

from filings_rag.psx import FILINGS, INTERMEDIATES


def test_pilot_reports_come_from_company_sites_only():
    hosts = {urlparse(f.url).hostname for f in FILINGS}
    assert all(h and not h.endswith("psx.com.pk") for h in hosts)
    assert all(f.url.startswith("https://") for f in FILINGS)


def test_pilot_names_are_unique():
    assert len({f.name for f in FILINGS}) == len(FILINGS)


def test_intermediates_are_pinned():
    assert all(len(digest) == 64 for digest in INTERMEDIATES.values())


def _page(n, heading, rows=12, cells=None):
    from filings_rag.parse import Line, ParsedPage

    lines = [Line(t, cells or [t], i, False) for i, t in enumerate(heading)]
    lines += [
        Line(f"Item {i} | 1,000 | 900", [f"Item {i}", "1,000", "900"], 100 + i, True) for i in range(rows)
    ]
    return ParsedPage(n, lines, None)


def test_psx_finder_reads_split_titles_and_keeps_bases_apart():
    from filings_rag.statements import psx_statement_pages

    pages = [
        _page(
            0, ["SIX YEARS AT A GLANCE", "STATEMENT OF FINANCIAL POSITION"]
        ),  # a summary, not the statement
        _page(1, ["UNCONSOLIDATED STATEMENT OF", "FINANCIAL POSITION", "AS AT JUNE 30, 2026"]),
        _page(2, ["Unconsolidated Statement of Profit or Loss"], rows=9),
        _page(3, ["Unconsolidated Statement of Cash Flows"]),
        _page(4, ["Consolidated Statement of Financial Position", "As at June 30, 2026"]),
        _page(5, ["As at June 30, 2026"]),  # continues the consolidated balance sheet
        _page(6, ["Consolidated Profit and Loss Account"]),
        _page(7, ["Consolidated Cash Flow Statement"]),
    ]
    assert psx_statement_pages(pages) == {
        "unconsolidated": {"balance_sheet": [1], "income_statement": [2], "cash_flow": [3]},
        "consolidated": {"balance_sheet": [4, 5], "income_statement": [6], "cash_flow": [7]},
    }


def test_psx_finder_reads_statements_printed_side_by_side():
    from filings_rag.parse import Line, ParsedPage
    from filings_rag.statements import _psx_titles

    head = [
        Line("x", ["unconsolidated statement", "unconsolidated statement"], 0, False),
        Line("x", ["of financial position", "of profit or loss"], 1, False),
    ]
    page = ParsedPage(0, head, None)
    assert _psx_titles(page) == {("balance_sheet", "unconsolidated"), ("income_statement", "unconsolidated")}


def test_rupee_units():
    from filings_rag.parse import Line, _units

    def units(*texts):
        return _units([Line(t, t.split(" | "), i, False) for i, t in enumerate(texts)])

    assert units("Rupees in ‘000") == "thousands"
    assert units("Note | (Rupees in thousand)") == "thousands"
    assert units("(Rs. ‘000s) | (Rs. ‘000s)") == "thousands"
    assert units("Rs. (Millions)") == "millions"
    assert units("(Amounts in thousand)") == "thousands"
    assert units("OPERATING ACTIVITIES | Rupees | Rupees") == "rupees"
    assert units("(in millions, except per share data)") == "millions"  # the FinanceBench rule wins
    assert units("Paid 5,000 rupees to a supplier") is None
