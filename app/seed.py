"""Load the labeled sample mailbox and pre-triage a slice so the desk is not empty."""

from __future__ import annotations

import json
from pathlib import Path

from app import db
from app.classifier import classify_rules
from app.pipeline import apply_policy

CORPUS = Path(__file__).resolve().parents[1] / "data" / "sample_emails.json"

# Left unseen so the worker, and the Run worker button, have something to do.
HOLD_FOR_INTAKE = {"m02", "m06", "m08", "m15", "m23", "m32", "m39", "m41"}


def load_corpus() -> list[dict]:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def seed_if_empty() -> int:
    if db.email_count():
        return 0
    emails = load_corpus()
    started = db.now()
    processed = 0
    leads = 0
    alerts = 0
    for email in emails:
        db.insert_email(email)
        if email["id"] in HOLD_FOR_INTAKE:
            continue
        outcome = apply_policy(email, classify_rules(email))
        processed += 1
        leads += 1 if outcome.get("lead") else 0
        alerts += 1 if outcome.get("alert") else 0
    db.insert_run(
        {
            "source": "startup",
            "started_at": started,
            "finished_at": db.now(),
            "processed": processed,
            "leads": leads,
            "alerts": alerts,
            "ingested": len(emails),
        }
    )
    return len(emails)


def reset_demo() -> int:
    db.clear_all()
    return seed_if_empty()
