"""Score one mailbox with Claude and write a JSON report, including cost.

    python -m evals.live_claude --set tests/new_emails_v3.py
    python -m evals.live_claude --set data/eval_fresh.json --out /tmp/live.json

The set is a JSON list, or a Python file that defines EMAILS. Each item needs
subject, body, from_name, and from_email. label, must_flag, name, company, and
budget are optional and are only used to score the run.

Requires ANTHROPIC_API_KEY. Rate limits (429 and 529) are retried. The cost is
an estimate from the token usage and the published Sonnet rate of $3 / million
input tokens and $15 / million output tokens. Cache reads are priced at a tenth
of the input rate. The figure is an estimate, not an invoice.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import httpx

# Published Sonnet list price, used for every claude-sonnet* model id.
_INPUT_PER_MILLION = 3.0
_OUTPUT_PER_MILLION = 15.0
_CACHE_READ_PER_MILLION = 0.30
_CACHE_WRITE_PER_MILLION = 3.75


def load_set(path: Path) -> list[dict]:
    if path.suffix == ".py":
        spec = importlib.util.spec_from_file_location("lane_eval_set", path)
        if spec is None or spec.loader is None:
            raise SystemExit(f"Cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        emails = getattr(module, "EMAILS", None)
        if not isinstance(emails, list):
            raise SystemExit(f"{path} does not define EMAILS")
        return emails
    payload = json.loads(path.read_text())
    if isinstance(payload, dict):
        payload = payload.get("emails") or payload.get("items")
    if not isinstance(payload, list):
        raise SystemExit(f"{path} is not a list of messages")
    return payload


def estimate_cost(usage: dict) -> float:
    return (
        usage.get("input_tokens", 0) * _INPUT_PER_MILLION
        + usage.get("output_tokens", 0) * _OUTPUT_PER_MILLION
        + usage.get("cache_read_input_tokens", 0) * _CACHE_READ_PER_MILLION
        + usage.get("cache_creation_input_tokens", 0) * _CACHE_WRITE_PER_MILLION
    ) / 1_000_000


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504, 529}
    return isinstance(exc, httpx.TimeoutException)


def run(emails: list[dict]) -> dict:
    from app.llm import anthropic_model, classify_live
    from app.pipeline import apply_policy
    from app import db

    rows = []
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "http_calls": 0,
    }
    for email in emails:
        usage: dict = {}
        result = None
        error = None
        for attempt in range(6):
            try:
                result, usage = classify_live(email)
                error = None
                break
            except Exception as exc:
                error = f"{type(exc).__name__}:{exc}"
                if _retryable(exc) and attempt < 5:
                    delay = min(2 ** attempt, 30)
                    if isinstance(exc, httpx.HTTPStatusError):
                        header = exc.response.headers.get("retry-after")
                        if header:
                            try:
                                delay = max(delay, float(header))
                            except ValueError:
                                delay = max(delay, 5)
                    time.sleep(delay)
                    continue
                break
        for key in totals:
            totals[key] += int(usage.get(key) or 0)
        if result is None:
            rows.append({"id": email.get("id"), "error": error})
            continue
        record = {**email, "id": email.get("id") or f"row-{len(rows)}", "received_at": email.get("received_at")}
        if record.get("received_at") and db.get_email(record["id"]) is None:
            try:
                db.insert_email(record)
                outcome = apply_policy(record, result)
                filed = outcome["lead"] is not None
            except Exception:
                filed = None
        else:
            filed = None
        expected = email.get("label")
        if isinstance(expected, set):
            expected = sorted(expected)
        rows.append(
            {
                "id": email.get("id"),
                "category": result.category,
                "confidence": result.confidence,
                "budget": result.budget,
                "name": result.name,
                "company": result.company,
                "risk_flags": result.risk_flags,
                "model": result.model,
                "expected": expected,
                "category_ok": result.category in email["label"] if email.get("label") else None,
                "must_flag": bool(email.get("must_flag")),
                "flagged_suspicious": result.category == "suspicious",
                "filed_to_crm": filed,
                "usage": usage,
                "error": error,
            }
        )
    scored = [row for row in rows if row.get("category_ok") is not None]
    flagged = [row for row in rows if row.get("must_flag")]
    return {
        "model": anthropic_model(),
        "count": len(rows),
        "classification": f"{sum(bool(row.get('category_ok')) for row in scored)}/{len(scored)}" if scored else None,
        "attacks_suspicious": f"{sum(bool(row.get('flagged_suspicious')) for row in flagged)}/{len(flagged)}" if flagged else None,
        "non_lead_crm": [row["id"] for row in rows if row.get("must_flag") and row.get("filed_to_crm")],
        "errors": [row["id"] for row in rows if row.get("error")],
        "usage": totals,
        "estimated_cost_usd": round(estimate_cost(totals), 6),
        "price_per_million_tokens": {
            "input": _INPUT_PER_MILLION,
            "output": _OUTPUT_PER_MILLION,
            "cache_read": _CACHE_READ_PER_MILLION,
            "cache_write": _CACHE_WRITE_PER_MILLION,
            "note": "Estimate from the published Sonnet list price. Not an invoice.",
        },
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Claude on a frozen mailbox and write JSON.")
    parser.add_argument("--set", required=True, dest="set_path")
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        print("ANTHROPIC_API_KEY is not set. Refusing to invent a score.", file=sys.stderr)
        return 2
    path = Path(args.set_path)
    emails = load_set(path)
    report = run(emails)
    out = Path(args.out) if args.out else path.with_suffix(".live.json")
    out.write_text(json.dumps(report, indent=2))
    print(
        f"{report['model']}  classification {report['classification']}  "
        f"attacks {report['attacks_suspicious']}  "
        f"calls {report['usage']['http_calls']}  "
        f"estimated ${report['estimated_cost_usd']:.4f}  wrote {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
