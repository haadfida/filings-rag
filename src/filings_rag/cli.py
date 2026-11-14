"""Command line for the benchmark: download data, run baselines, validate the judge."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from filings_rag import data
from filings_rag.benchmark import CONTRADICTORY_KEYS, load_documents, load_questions, split_of
from filings_rag.llm import DEFAULT_MODEL, PRICES, load_dotenv

EFFORTS = ("low", "medium", "high", "xhigh", "max")


def cmd_data(_: argparse.Namespace) -> int:
    report = data.download()
    print(f"downloaded {len(report.downloaded)}, already present {len(report.skipped)}")
    for p in report.problems:
        print(f"PROBLEM: {p}", file=sys.stderr)
    print("data OK" if report.ok else f"{len(report.problems)} problem(s)")
    return 0 if report.ok else 1


def cmd_stats(_: argparse.Namespace) -> int:
    qs = load_questions()
    docs = load_documents()
    n_docs, n_companies = len({q.doc_name for q in qs}), len({q.company for q in qs})
    print(f"{len(qs)} questions, {n_docs} documents, {n_companies} companies")
    print("question types:", dict(Counter(q.question_type for q in qs)))
    print("document types:", dict(Counter(docs[q.doc_name].doc_type for q in qs)))
    print("split:", dict(Counter(split_of(q) for q in qs)))
    print("evidence items:", sum(len(q.evidence) for q in qs))
    print(f"contradictory keys excluded from the clean score: {len(CONTRADICTORY_KEYS)}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from filings_rag import runner

    questions = runner.select(args.split, args.limit, args.ids.split(",") if args.ids else None)
    name = args.name or f"{args.mode}_{args.model}_{args.effort}_{args.split}"
    summary = runner.run(
        name, args.mode, questions, args.model, args.effort, args.judge_model, args.judge_effort, args.workers
    )
    print(json.dumps(summary, indent=2))
    return 0


def cmd_validate_judge(args: argparse.Namespace) -> int:
    from filings_rag import runner

    print(json.dumps(runner.validate_judge(args.n, args.model, args.effort, args.workers), indent=2))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from filings_rag import runner

    names = args.names or sorted(p.parent.name for p in runner.RUNS_DIR.glob("*/answers.jsonl"))
    for name in names:
        s = runner.resummarise(name)
        print(f"{name}: {json.dumps(s['all']['scores'])}")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    parser = argparse.ArgumentParser(prog="filings-rag")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("data", help="download and verify the FinanceBench open set").set_defaults(func=cmd_data)
    sub.add_parser("stats", help="summarise the downloaded benchmark").set_defaults(func=cmd_stats)

    r = sub.add_parser("run", help="answer and grade questions with a baseline (calls the API)")
    r.add_argument("--mode", choices=("closed_book", "oracle", "bm25"), required=True)
    r.add_argument("--model", choices=sorted(PRICES), default=DEFAULT_MODEL)
    r.add_argument("--effort", choices=EFFORTS, default="medium")
    r.add_argument("--judge-model", choices=sorted(PRICES), default=DEFAULT_MODEL)
    r.add_argument("--judge-effort", choices=EFFORTS, default="medium")
    r.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    r.add_argument("--limit", type=int)
    r.add_argument("--ids", help="comma-separated question ids (overrides --split)")
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--name", help="run directory name under runs/ (default from the settings)")
    r.set_defaults(func=cmd_run)

    rep = sub.add_parser("report", help="rebuild run summaries from saved answers (no API calls)")
    rep.add_argument("names", nargs="*", help="run names under runs/ (default: all)")
    rep.set_defaults(func=cmd_report)

    v = sub.add_parser("validate-judge", help="grade human-labelled answers and measure agreement")
    v.add_argument("--n", type=int, default=150, help="sample size, balanced across the three labels")
    v.add_argument("--model", choices=sorted(PRICES), default=DEFAULT_MODEL)
    v.add_argument("--effort", choices=EFFORTS, default="medium")
    v.add_argument("--workers", type=int, default=4)
    v.set_defaults(func=cmd_validate_judge)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
