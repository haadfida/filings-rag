"""Run a baseline over benchmark questions, grade it, and summarise it. Runs are resumable.

Each run writes to `runs/<name>/`:
  answers.jsonl  one line per question: the answer, pages given to the model, tokens, cost, latency
  grades.jsonl   one line per graded answer: label and the judge's reason
  summary.json   scores by split, with and without the contradictory keys, cost and latency
Re-running the same name skips questions already answered or graded.
"""

from __future__ import annotations

import json
import random
import statistics
import threading
from collections import Counter
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from filings_rag import answer as answer_mod
from filings_rag import judge as judge_mod
from filings_rag.benchmark import Question, load_labelled_answers, load_questions, split_of
from filings_rag.citations import cited_pages, cites_evidence
from filings_rag.llm import LLM

RUNS_DIR = Path(__file__).resolve().parents[2] / "runs"


def _read(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    rows = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return {r["key"]: r for r in rows}


def _parallel(items: Iterable, fn: Callable[[object], dict], out: Path, workers: int) -> None:
    lock = threading.Lock()
    out.parent.mkdir(parents=True, exist_ok=True)
    items = list(items)
    done = 0
    written: set[int] = set()
    with out.open("a", encoding="utf-8") as f:

        def write(i: int, row: dict) -> None:
            nonlocal done
            with lock:
                f.write(json.dumps(row) + "\n")
                f.flush()
                written.add(i)
                done += 1
                print(f"  {done}/{len(items)} {row['key']} {row.get('label') or row.get('stop_reason')}")

        pool = ThreadPoolExecutor(max_workers=workers)
        futures = {pool.submit(fn, item): i for i, item in enumerate(items)}
        try:
            for fut in as_completed(futures):
                write(futures[fut], fut.result())
        except BaseException:
            # Ctrl-C or a crash: cancel queued calls so they are not paid for, let the few in flight
            # finish, and keep their rows so a resume does not pay for them again.
            pool.shutdown(wait=True, cancel_futures=True)
            for fut, i in futures.items():
                if i not in written and fut.done() and not fut.cancelled() and fut.exception() is None:
                    write(i, fut.result())
            raise
        pool.shutdown()


def select(split: str, limit: int | None, ids: list[str] | None) -> list[Question]:
    qs = load_questions()
    if ids:
        qs = [q for q in qs if q.id in set(ids)]
    elif split != "all":
        qs = [q for q in qs if split_of(q) == split]
    return qs[:limit] if limit else qs


def run(
    name: str,
    mode: str,
    questions: list[Question],
    model: str,
    effort: str,
    judge_model: str,
    judge_effort: str,
    workers: int = 4,
) -> dict:
    run_dir = RUNS_DIR / name
    llm = LLM()
    config = {
        "mode": mode,
        "pipeline": answer_mod.pipeline(mode),
        "model": model,
        "effort": effort,
        "judge_model": judge_model,
        "judge_effort": judge_effort,
        "judge_version": judge_mod.JUDGE_VERSION,
        "fingerprint": answer_mod.fingerprint(mode),
    }
    cfg_path = run_dir / "config.json"
    if cfg_path.exists() and json.loads(cfg_path.read_text()) != config:
        raise SystemExit(f"run {name!r} exists with a different config; pick another name")
    run_dir.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(config, indent=2) + "\n")

    answers_path = run_dir / "answers.jsonl"
    done = _read(answers_path)

    def do_answer(q: Question) -> dict:
        try:
            ctx, res = answer_mod.answer(llm, q, mode, model, effort)
        except Exception as e:  # recorded and retried on the next run of this name
            return {"key": q.id, "error": f"{type(e).__name__}: {e}"}
        if res.stop_reason == "max_tokens":  # cut off, not a wrong answer: an error row, retried next run
            return {"key": q.id, "error": "answer cut off at max_tokens", "cost": res.cost}
        data = res.data or {}
        return {
            "key": q.id,
            "split": split_of(q),
            "answer": data.get("answer"),
            "cannot_answer": data.get("cannot_answer"),
            "stop_reason": res.stop_reason,
            "pages": [[d, p] for d, p in ctx.pages],
            "usage": res.usage.as_dict(),
            "cost": res.cost,
            "latency_s": round(res.latency_s, 2),
            "request_id": res.request_id,
        }

    todo = [q for q in questions if q.id not in done or "error" in done[q.id]]
    print(f"answering {len(todo)} question(s) ({len(questions) - len(todo)} already done)")
    _parallel(todo, do_answer, answers_path, workers)

    answers = _read(answers_path)
    grades_path = run_dir / "grades.jsonl"
    graded = _read(grades_path)
    by_id = {q.id: q for q in questions}

    def do_grade(qid: str) -> dict:
        a = answers[qid]
        if a.get("answer") is None:  # model declined or was cut off: no text to grade
            label = "refusal" if a.get("stop_reason") == "refusal" else "incorrect"
            return {
                "key": qid,
                "label": label,
                "reason": f"no answer (stop_reason={a.get('stop_reason')})",
                "cost": 0.0,
            }
        try:
            res = judge_mod.grade(llm, by_id[qid], a["answer"], judge_model, judge_effort)
        except Exception as e:
            return {"key": qid, "error": f"{type(e).__name__}: {e}"}
        if not res.data:  # no label: an error row, so the next run of this name retries it
            return {
                "key": qid,
                "error": f"judge returned no label (stop_reason={res.stop_reason})",
                "cost": res.cost,
            }
        return {"key": qid, "label": res.data["label"], "reason": res.data["reason"], "cost": res.cost}

    to_grade = [
        qid
        for qid in by_id
        if qid in answers and "error" not in answers[qid] and (qid not in graded or "error" in graded[qid])
    ]
    print(f"grading {len(to_grade)} answer(s)")
    _parallel(to_grade, do_grade, grades_path, workers)

    summary = summarise(questions, _read(answers_path), _read(grades_path), config)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def _scores(qs: list[Question], answers: dict[str, dict], grades: dict[str, dict]) -> dict:
    """Shares of correct, incorrect and refused answers, plus citation-based measures.

    grounded: correct and cites at least one evidence page. cites_a_page: cites any page at all.
    ungraded: questions with no label yet; shares are over graded questions only, so it should be 0.
    """
    graded = [q for q in qs if q.id in grades and grades[q.id].get("label")]
    n = len(graded)
    c = Counter(grades[q.id]["label"] for q in graded)
    grounded = sum(
        grades[q.id]["label"] == "correct" and cites_evidence(q, answers[q.id].get("answer")) for q in graded
    )
    cites = sum(bool(cited_pages(answers[q.id].get("answer"))) for q in graded)

    def share(k: int) -> float | None:
        return round(k / n, 3) if n else None

    return {
        "n": n,
        "ungraded": len(qs) - n,
        "correct": share(c["correct"]),
        "grounded": share(grounded),
        "incorrect": share(c["incorrect"]),
        "refusal": share(c["refusal"]),
        "cites_a_page": share(cites),
    }


def summarise(questions: list[Question], answers: dict, grades: dict, config: dict) -> dict:
    ok = [q for q in questions if q.id in answers and "error" not in answers[q.id]]
    summary: dict = {"config": config}
    for split in ("dev", "test", "all"):
        in_split = [q for q in ok if split == "all" or split_of(q) == split]
        clean = [q for q in in_split if not q.key_is_contradictory]
        summary[split] = {
            "scores": _scores(in_split, answers, grades),
            "scores_clean_key": _scores(clean, answers, grades),
        }

    hits = []
    for q in ok:
        given = {(d, p) for d, p in answers[q.id]["pages"]}
        if given:
            hits.append(any((e.doc_name, e.page) in given for e in q.evidence))
    if hits:
        summary["evidence_page_given_rate"] = round(sum(hits) / len(hits), 3)

    answer_cost = sum(answers[q.id]["cost"] for q in ok)
    judge_cost = sum(grades[q.id].get("cost", 0.0) for q in ok if q.id in grades)  # same questions
    lat = [answers[q.id]["latency_s"] for q in ok]
    summary["cost_usd"] = {
        "answers": round(answer_cost, 4),
        "judge": round(judge_cost, 4),
        "per_question": round((answer_cost + judge_cost) / len(ok), 4) if ok else None,
    }
    summary["latency_s"] = {"median": statistics.median(lat) if lat else None, "max": max(lat, default=None)}
    summary["errors"] = len(questions) - len(ok)
    return summary


def validate_judge(
    n: int, model: str, effort: str, workers: int = 4, seed: int = 7, exclude_seed: int | None = None
) -> dict:
    """Grade a balanced sample of the paper's human-labelled answers and measure agreement.

    exclude_seed: leave out the answers that seed's sample drew, for an out-of-sample check of a rubric
    that was revised after reading its disagreements on that sample.
    """
    qs = {q.id: q for q in load_questions()}
    pool = [a for a in load_labelled_answers() if a.question_id in qs and a.model_answer.strip()]
    if exclude_seed is not None:
        seen = {(a.source, a.question_id) for a in _judge_sample(pool, n, exclude_seed)}
        pool = [a for a in pool if (a.source, a.question_id) not in seen]
    sample = _judge_sample(pool, n, seed)

    name = f"judge-validation_{judge_mod.JUDGE_VERSION}_{model}_{effort}_n{n}_seed{seed}"
    if exclude_seed is not None:
        name += f"_excl{exclude_seed}"
    out = RUNS_DIR / name / "grades.jsonl"
    graded = _read(out)
    llm = LLM()

    def key(a) -> str:
        return f"{a.source}:{a.question_id}"

    def do(a) -> dict:
        try:
            res = judge_mod.grade(llm, qs[a.question_id], a.model_answer, model, effort)
        except Exception as e:
            return {"key": key(a), "error": f"{type(e).__name__}: {e}"}
        if not res.data:
            return {"key": key(a), "error": f"judge returned no label (stop_reason={res.stop_reason})"}
        data = res.data
        return {
            "key": key(a),
            "human": a.label,
            "label": data["label"],
            "reason": data["reason"],
            "cost": res.cost,
        }

    todo = [a for a in sample if key(a) not in graded or "error" in graded[key(a)]]
    print(f"judging {len(todo)} labelled answer(s)")
    _parallel(todo, do, out, workers)

    rows = [r for r in _read(out).values() if "error" not in r and r.get("label")]
    agree = sum(r["human"] == r["label"] for r in rows)
    confusion = Counter((r["human"], r["label"]) for r in rows)
    result = {
        "n": len(rows),
        "agreement": round(agree / len(rows), 3) if rows else None,
        "cohens_kappa": _kappa(rows),
        "confusion_human_to_judge": {f"{h}->{j}": c for (h, j), c in sorted(confusion.items())},
        "cost_usd": round(sum(r["cost"] for r in rows), 4),
    }
    (out.parent / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def _judge_sample(pool: list, n: int, seed: int) -> list:
    """n // 3 answers per human label, drawn with a fixed seed."""
    rng = random.Random(seed)
    sample = []
    for label in judge_mod.LABELS:
        group = [a for a in pool if a.label == label]
        sample += rng.sample(group, min(len(group), n // 3))
    return sample


def _kappa(rows: list[dict]) -> float | None:
    n = len(rows)
    if not n:
        return None
    po = sum(r["human"] == r["label"] for r in rows) / n
    h = Counter(r["human"] for r in rows)
    j = Counter(r["label"] for r in rows)
    pe = sum(h[label] * j[label] for label in judge_mod.LABELS) / (n * n)
    return round((po - pe) / (1 - pe), 3) if pe < 1 else None


def resummarise(name: str) -> dict:
    """Rebuild a run's summary.json from its saved answers and grades. Makes no API calls."""
    run_dir = RUNS_DIR / name
    config = json.loads((run_dir / "config.json").read_text())
    answers = _read(run_dir / "answers.jsonl")
    questions = [q for q in load_questions() if q.id in answers]
    summary = summarise(questions, answers, _read(run_dir / "grades.jsonl"), config)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def mcnemar_p(only_a: int, only_b: int) -> float:
    """Exact two-sided McNemar test: the chance of a split at least this uneven if the two runs were
    equally good, given how many questions they disagree on."""
    from math import comb

    n = only_a + only_b
    if n == 0:
        return 1.0
    tail = sum(comb(n, j) for j in range(min(only_a, only_b) + 1)) / 2**n
    return min(1.0, 2 * tail)


def compare(name_a: str, name_b: str, split: str = "test") -> dict:
    """Paired comparison of two runs on the same questions, for correct and for grounded answers."""
    qs = {q.id: q for q in load_questions() if split == "all" or split_of(q) == split}
    runs = []
    for name in (name_a, name_b):
        answers, grades = _read(RUNS_DIR / name / "answers.jsonl"), _read(RUNS_DIR / name / "grades.jsonl")
        runs.append((answers, grades))
    common = [i for i in qs if all(i in g and g[i].get("label") for _, g in runs)]

    def outcome(run, qid: str, measure: str) -> bool:
        answers, grades = run
        ok = grades[qid]["label"] == "correct"
        return ok and cites_evidence(qs[qid], answers[qid].get("answer")) if measure == "grounded" else ok

    out: dict = {"a": name_a, "b": name_b, "split": split, "questions": len(common)}
    for measure in ("correct", "grounded"):
        a = [outcome(runs[0], i, measure) for i in common]
        b = [outcome(runs[1], i, measure) for i in common]
        only_a = sum(x and not y for x, y in zip(a, b, strict=True))
        only_b = sum(y and not x for x, y in zip(a, b, strict=True))
        out[measure] = {
            "a": round(sum(a) / len(common), 3) if common else None,
            "b": round(sum(b) / len(common), 3) if common else None,
            "only_a": only_a,
            "only_b": only_b,
            "p_mcnemar": round(mcnemar_p(only_a, only_b), 4),
        }
    return out
