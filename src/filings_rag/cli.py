"""Command line: `filings-rag data` downloads and verifies the benchmark; `stats` summarises it."""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from filings_rag import data
from filings_rag.benchmark import CONTRADICTORY_KEYS, load_documents, load_questions


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
    used = {q.doc_name for q in qs}
    print(f"{len(qs)} questions, {len(used)} documents, {len({q.company for q in qs})} companies")
    print("question types:", dict(Counter(q.question_type for q in qs)))
    print("document types:", dict(Counter(docs[q.doc_name].doc_type for q in qs)))
    print("evidence items:", sum(len(q.evidence) for q in qs))
    print(f"contradictory keys excluded from the clean score: {len(CONTRADICTORY_KEYS)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="filings-rag")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("data", help="download and verify the FinanceBench open set").set_defaults(func=cmd_data)
    sub.add_parser("stats", help="summarise the downloaded benchmark").set_defaults(func=cmd_stats)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
