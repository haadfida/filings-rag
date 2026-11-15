"""Behaviour found missing by the ultrareview: interrupts, cut-off answers, caches and prompt versions."""

import json
import threading
import time

import pytest

from filings_rag import judge, rewrite, runner
from filings_rag.cachefile import atomic_write_text, lock_for
from filings_rag.llm import MAX_TOKENS, Result, Usage
from filings_rag.statements import statements_for


def test_interrupt_cancels_queued_work_and_keeps_finished_rows(tmp_path, monkeypatch):
    calls = []
    calls_lock = threading.Lock()

    def slow(item):
        with calls_lock:
            calls.append(item)
        time.sleep(0.05)
        return {"key": f"q{item}"}

    def ctrl_c(*_args, **_kwargs):  # the first progress line stands in for the user pressing Ctrl-C
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "print", ctrl_c, raising=False)
    out = tmp_path / "answers.jsonl"
    with pytest.raises(KeyboardInterrupt):
        runner._parallel(range(40), slow, out, workers=2)
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(calls) < 10, "queued items kept running after the interrupt"
    assert len(rows) >= 1 and len({r["key"] for r in rows}) == len(rows)
    assert {r["key"] for r in rows} <= {f"q{i}" for i in calls}


def test_atomic_write_leaves_no_temp_files(tmp_path):
    path = tmp_path / "cache" / "x.json"
    atomic_write_text(path, '{"a": 1}')
    atomic_write_text(path, '{"a": 2}')
    assert json.loads(path.read_text()) == {"a": 2}
    assert [p.name for p in path.parent.iterdir()] == ["x.json"]


def test_lock_for_is_one_lock_per_key():
    assert lock_for("parse:A") is lock_for("parse:A")
    assert lock_for("parse:A") is not lock_for("parse:B")


def test_eps_cue_needs_a_word_boundary():
    assert statements_for("What steps did the company take to cut costs?") == []
    assert statements_for("What was diluted EPS in FY2022?") == ["income_statement"]


def test_output_budget_grows_with_effort():
    budgets = [MAX_TOKENS[e] for e in ("low", "medium", "high", "xhigh", "max")]
    assert budgets == sorted(budgets) and MAX_TOKENS["medium"] == 16000  # medium: the published runs


def test_empty_rewrite_is_an_error_not_a_silent_fallback():
    class NoQueries:
        def json(self, **_kwargs):
            usage = Usage(input_tokens=100, output_tokens=10)
            return Result({"queries": []}, "end_turn", usage, rewrite.REWRITE_MODEL, 0.1, None)

    with pytest.raises(RuntimeError, match="no queries"):
        rewrite.rewrites("A question no cache has seen 7f3c?", "Nobody Inc", llm=NoQueries())


def test_judge_prompt_is_versioned():
    # If this fails, the rubric, schema or judge prompt changed: bump JUDGE_VERSION and re-validate.
    assert (judge.JUDGE_VERSION, judge.PROMPT_FINGERPRINT) == ("v2", "2018dc5ababd")
