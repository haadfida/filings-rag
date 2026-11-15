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


def test_ppne_cue():
    assert statements_for("Did Pfizer grow its PPNE between FY20 and FY21?") == ["balance_sheet"]


def test_choose_prefers_earliest_tight_cluster():
    from filings_rag.statements import _choose

    cands = {
        "balance_sheet": [(56, 30), (94, 34), (173, 40)],  # real, guarantor note, subsidiary exhibit
        "income_statement": [(57, 25), (174, 30)],
        "cash_flow": [(59, 40), (175, 45)],
    }
    assert _choose(cands) == {"balance_sheet": 56, "income_statement": 57, "cash_flow": 59}
    assert _choose({"balance_sheet": [], "income_statement": [], "cash_flow": []}) == {}
    # With no tight cluster, the tightest combination wins.
    assert _choose({"balance_sheet": [(10, 20), (60, 20)], "cash_flow": [(50, 20)]}) == {
        "balance_sheet": 60,
        "cash_flow": 50,
    }
