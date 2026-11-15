from filings_rag.statements import TITLES, statements_for


def test_question_cues():
    assert statements_for("What is the FY2018 capital expenditure amount for 3M?") == ["cash_flow"]
    assert statements_for("Does AMD have a healthy quick ratio for FY22?") == ["balance_sheet"]
    assert set(statements_for("What is AES's FY2022 return on assets (ROA)?")) == {
        "balance_sheet",
        "income_statement",
    }
    assert statements_for("What are major acquisitions that AMCOR has done in FY2023?") == []


def test_titles():
    assert TITLES["balance_sheet"].search("CONSOLIDATED BALANCE SHEETS")
    assert TITLES["balance_sheet"].search("Consolidated Statements of Financial Position")
    assert TITLES["income_statement"].search("CONSOLIDATED STATEMENTS OF OPERATIONS")
    assert TITLES["cash_flow"].search("Consolidated Statement of Cash Flows")
    assert not TITLES["cash_flow"].search("Operating cash flow was strong")
