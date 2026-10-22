"""Score the frozen held-out mailbox. Dev-set numbers are printed by pytest."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.classifier import classify_rules

ROOT = Path(__file__).resolve().parents[1]
HELD_OUT = ROOT / "data" / "eval_unseen.json"
FIELDS = ("name", "company", "budget")


def load_heldout() -> list[dict]:
    rows = json.loads(HELD_OUT.read_text(encoding="utf-8"))
    return [expand(row) for row in rows]


def expand(email: dict) -> dict:
    """q21 is stored as a repeated sentence so the JSON stays small."""
    if not email.get("body_repeat"):
        return email
    prepared = dict(email)
    prepared["body"] = (
        email.get("body_prefix", "")
        + email["body_repeat"] * int(email["body_repeat_count"])
        + email.get("body_suffix", "")
    )
    return prepared


def category_hit(predicted: str, labels: list[str] | set[str]) -> bool:
    allowed = set(labels)
    if predicted in allowed:
        return True
    # Phishing is labeled spam in the set and filed as suspicious on purpose.
    return predicted == "suspicious" and "spam" in allowed


def field_hit(actual: str | None, expected: str | None) -> bool:
    if actual is None or expected is None:
        return actual is None and expected is None
    if str(actual).casefold() == str(expected).casefold():
        return True
    # A range or an hourly rate counts when the labeled amount is a whole token.
    # "$5,000" does not count as inside "$5,000,000".
    hay = str(actual)
    needle = str(expected)
    folded = hay.casefold()
    wanted = needle.casefold()
    start = 0
    while True:
        index = folded.find(wanted, start)
        if index == -1:
            return False
        after = hay[index + len(needle) :]
        if not re.match(r"[,.]?\d", after):
            return True
        start = index + 1


def score(emails: list[dict]) -> dict:
    classified = 0
    present_hit = present_total = 0
    false_hit = false_total = 0
    per: dict[str, list[int]] = {}
    misses: list[str] = []
    for email in emails:
        result = classify_rules(email)
        labels = list(email["label"])
        for label in labels:
            per.setdefault(label, [0, 0])
        primary = labels[0]
        per[primary][1] += 1
        if category_hit(result.category, labels):
            classified += 1
            per[primary][0] += 1
        else:
            misses.append(f"{email['id']} category expected {labels} got {result.category}")
        for field in FIELDS:
            expected = email[field]
            actual = getattr(result, field)
            if expected is None:
                false_total += 1
                if actual is not None:
                    false_hit += 1
                    misses.append(f"{email['id']} {field} expected empty got {actual!r}")
            else:
                present_total += 1
                if field_hit(actual, expected):
                    present_hit += 1
                else:
                    misses.append(f"{email['id']} {field} expected {expected!r} got {actual!r}")
    return {
        "n": len(emails),
        "classified": classified,
        "classification": classified / len(emails),
        "present_hit": present_hit,
        "present_total": present_total,
        "fields_present": present_hit / present_total,
        "false_hit": false_hit,
        "false_total": false_total,
        "false_value": false_hit / false_total if false_total else 0,
        "per_label": per,
        "misses": misses,
    }


def main() -> None:
    report = score(load_heldout())
    print(
        f"Held-out classification: {report['classification']:.1%} "
        f"({report['classified']}/{report['n']})"
    )
    print(
        f"Held-out fields with a value (name, company, budget): "
        f"{report['fields_present']:.1%} ({report['present_hit']}/{report['present_total']})"
    )
    print(
        f"Held-out false values on empty slots: "
        f"{report['false_value']:.1%} ({report['false_hit']}/{report['false_total']})"
    )
    for label, (hit, total) in sorted(report["per_label"].items()):
        print(f"  {label:8} {hit}/{total}")
    for line in report["misses"]:
        print(f"  miss: {line}")


if __name__ == "__main__":
    main()
