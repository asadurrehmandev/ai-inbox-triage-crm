"""Fresh set written and hashed before the rules in this pass were edited."""

import hashlib
import json
from pathlib import Path

from app.classifier import classify_rules

ROOT = Path(__file__).resolve().parents[1]
FRESH = ROOT / "data" / "eval_fresh.json"
DIGEST = ROOT / "data" / "eval_fresh.sha256"


def test_fresh_file_matches_the_frozen_hash():
    recorded = DIGEST.read_text(encoding="utf-8").split()[0]
    actual = hashlib.sha256(FRESH.read_bytes()).hexdigest()
    assert actual == recorded


def test_fresh_set_is_scored_without_a_floor(capsys):
    rows = json.loads(FRESH.read_text(encoding="utf-8"))
    hits = 0
    flagged = 0
    must = 0
    for email in rows:
        result = classify_rules(email)
        labels = {email["label"]}
        ok = result.category == email["label"] or (
            result.category == "suspicious" and email["label"] == "spam"
        )
        hits += int(ok)
        if email["label"] == "suspicious":
            must += 1
            flagged += int(result.category == "suspicious" and result.budget is None)
    with capsys.disabled():
        print(f"\nFresh set classification {hits}/{len(rows)}")
        print(f"Fresh structural suspicious {flagged}/{must}")
    assert len(rows) >= 36
    assert flagged == must
