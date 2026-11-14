from filings_rag.chunk import _segments, chunk_page
from filings_rag.parse import Line, ParsedPage, _cells, _is_row, _visual_lines


def word(x0, y0, text, w=None, h=8.0):
    width = w if w is not None else 4.0 * len(text)
    return (x0, y0, x0 + width, y0 + h, text, 0, 0, 0)


def test_cells_split_on_wide_gaps_and_keep_dollar_with_number():
    line = [
        word(10, 100, "Depreciation"),
        word(62, 100, "and"),
        word(78, 100, "amortization"),
        word(300, 100, "$"),
        word(306, 100, "1,488"),
        word(400, 100, "1,544"),
    ]
    assert _cells(line) == ["Depreciation and amortization", "$1,488", "1,544"]


def test_visual_lines_group_by_vertical_centre():
    words = [
        word(10, 100, "Revenue"),
        word(300, 101, "5,363"),
        word(10, 120, "Costs"),
        word(300, 119.5, "(370)"),
    ]
    lines = _visual_lines(words)
    assert [[w[4] for w in ln] for ln in lines] == [["Revenue", "5,363"], ["Costs", "(370)"]]


def test_row_detection():
    assert _is_row(["Total net sales", "$34,229", "$32,765"])
    assert _is_row(["(Millions)", "2018", "2017", "2016"])
    assert not _is_row(["Total assets were $220 billion as of July 2, 2023."])
    assert _is_row(["2018", "2017"])  # a bare header of years counts as a row


def _line(text: str) -> Line:
    cells = text.split(" | ")
    return Line(text, cells, 0.0, _is_row(cells))


def test_table_survives_long_label_lines_and_carries_years():
    lines = [
        _line(t)
        for t in [
            "Consolidated Statement of Cash Flows",
            "(Millions) | 2018 | 2017",
            "Net income | $5,363 | $4,869",
            "Adjustments to reconcile net income including noncontrolling interest to net cash",
            "provided by operating activities",
            "Depreciation and amortization | 1,488 | 1,544",
            "The accompanying notes are an integral part of this statement.",
        ]
    ]
    kinds = [k for k, _ in _segments(lines)]
    assert kinds == ["prose", "table", "prose"]
    chunks = chunk_page("DOC", ParsedPage(5, lines, "millions"))
    table = next(c for c in chunks if c.kind == "table")
    assert "Depreciation and amortization | 1,488" in table.text
    assert "(Amounts in millions unless stated otherwise)" in table.text
    assert table.text.startswith("Consolidated Statement of Cash Flows")
    assert table.page == 5
