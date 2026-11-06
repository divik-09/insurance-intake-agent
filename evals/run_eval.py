"""Measure extraction accuracy against labelled emails.

    python -m evals.run_eval --provider heuristic
    python -m evals.run_eval --provider anthropic --model claude-sonnet-5-5
    python -m evals.run_eval --provider openai

Scoring is per field. "Not stated" is a real answer: if the email doesn't give the
revenue and the extractor returns null, that field is *correct*; if it invents a
number, it's wrong. Coverage types are compared as sets.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.extraction import extract_submission
from app.llm import build_llm
from app.schemas import Submission

FIELDS = ["business_name", "industry", "state", "employee_count", "annual_revenue", "coverage_types"]
ROOT = Path(__file__).resolve().parent.parent


def _norm_name(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"[^a-z0-9]", "", value.lower().replace("&", "and"))


def field_correct(field: str, got: object, expected: object) -> bool:
    if field == "business_name":
        return _norm_name(got) == _norm_name(expected)  # type: ignore[arg-type]
    if field == "coverage_types":
        return set(got or []) == set(expected or [])  # type: ignore[arg-type]
    return got == expected


def predicted_fields(sub: Submission) -> dict:
    d = sub.model_dump(mode="json")
    return {f: d[f] for f in FIELDS}


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run(provider: str, model: str | None, data: Path) -> dict:
    llm = build_llm(provider, model)
    rows = load_rows(data)
    per_field = {f: 0 for f in FIELDS}
    exact_emails = 0
    failures: list[dict] = []
    errors = 0

    for row in rows:
        try:
            got = predicted_fields(extract_submission(llm, row["email"]))
        except Exception as exc:  # an LLM/API failure counts as a miss on every field
            errors += 1
            got = {f: "<error>" for f in FIELDS}
            failures.append({"id": row["id"], "field": "*", "expected": "-", "got": f"error: {exc}"})
        all_ok = True
        for f in FIELDS:
            if field_correct(f, got[f], row["expected"][f]):
                per_field[f] += 1
            else:
                all_ok = False
                failures.append({"id": row["id"], "field": f, "expected": row["expected"][f], "got": got[f]})
        exact_emails += all_ok

    n = len(rows)
    total_slots = n * len(FIELDS)
    correct_slots = sum(per_field.values())
    return {
        "provider": provider,
        "model": getattr(llm, "model", "regex-baseline"),
        "emails": n,
        "field_slots": total_slots,
        "overall_field_accuracy": round(correct_slots / total_slots, 4),
        "fully_correct_emails": exact_emails,
        "per_field_accuracy": {f: round(c / n, 4) for f, c in per_field.items()},
        "errors": errors,
        "failures": failures,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def print_report(res: dict) -> None:
    print(f"\nProvider: {res['provider']}   Model: {res['model']}   Emails: {res['emails']}")
    print("-" * 52)
    for f, acc in res["per_field_accuracy"].items():
        print(f"{f:<18} {acc * 100:5.1f}%")
    print("-" * 52)
    print(f"{'OVERALL (fields)':<18} {res['overall_field_accuracy'] * 100:5.1f}%  "
          f"({round(res['overall_field_accuracy'] * res['field_slots'])}/{res['field_slots']})")
    print(f"{'Fully correct':<18} {res['fully_correct_emails']}/{res['emails']} emails")
    if res["failures"]:
        print("\nMisses:")
        for m in res["failures"]:
            print(f"  {m['id']}  {m['field']:<16} expected={m['expected']!r}  got={m['got']!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", default="heuristic", choices=["heuristic", "anthropic", "openai"])
    parser.add_argument("--model", default=None)
    parser.add_argument("--data", type=Path, default=ROOT / "data" / "test_emails.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "evals" / "results")
    parser.add_argument("--min-accuracy", type=float, default=None,
                        help="exit non-zero if overall field accuracy is below this (for CI)")
    args = parser.parse_args()

    res = run(args.provider, args.model, args.data)
    print_report(res)

    args.out.mkdir(parents=True, exist_ok=True)
    out_file = args.out / f"{args.provider}.json"
    out_file.write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(f"\nSaved {out_file.relative_to(ROOT) if out_file.is_relative_to(ROOT) else out_file}")

    if args.min_accuracy is not None and res["overall_field_accuracy"] < args.min_accuracy:
        print(f"FAIL: accuracy below {args.min_accuracy:.0%}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
