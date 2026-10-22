"""Accuracy of the no-key classifier against the labeled mailbox."""

import json
from pathlib import Path

import pytest

from app.classifier import classify_rules
from app.llm import classification_from_payload, select_provider

CORPUS = Path(__file__).resolve().parents[1] / "data" / "sample_emails.json"
FIELDS = ("name", "company", "budget", "intent")


def load_emails() -> list[dict]:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def test_labeled_set_covers_every_category():
    emails = load_emails()
    assert len(emails) >= 40
    labels = {email["label"] for email in emails}
    assert labels == {"lead", "support", "invoice", "spam", "urgent"}


def test_classification_accuracy(capsys):
    emails = load_emails()
    mismatches = []
    correct = 0
    per_label: dict[str, list[int]] = {}
    for email in emails:
        per_label.setdefault(email["label"], [0, 0])
        per_label[email["label"]][1] += 1
        result = classify_rules(email)
        # A lookalike labeled spam is filed as suspicious. That is the intended review state.
        hit = result.category == email["label"] or (
            result.category == "suspicious" and email["label"] == "spam"
        ) or (
            email["label"] == "urgent"
            and result.category == "review"
            and result.suggested_category == "urgent"
        )
        if hit:
            correct += 1
            per_label[email["label"]][0] += 1
        else:
            mismatches.append(
                f"{email['id']} expected {email['label']} got {result.category} ({email['subject']})"
            )
    accuracy = correct / len(emails)
    exact = sum(1 for email in emails if classify_rules(email).category == email["label"])
    with capsys.disabled():
        print(
            f"\nClassification, spam-as-suspicious and first-contact urgent-as-review counted: "
            f"{accuracy:.1%} ({correct}/{len(emails)})"
        )
        print(f"Exact label match: {exact}/{len(emails)}")
        for label, (hit, total) in sorted(per_label.items()):
            print(f"  {label:8} {hit}/{total}")
        for line in mismatches:
            print(f"  mismatch: {line}")
    assert accuracy >= 0.90


def test_extraction_accuracy(capsys):
    emails = load_emails()
    hits = {field: 0 for field in FIELDS}
    misses = []
    for email in emails:
        result = classify_rules(email)
        for field in FIELDS:
            actual = getattr(result, field)
            expected = email[field]
            if _same(actual, expected):
                hits[field] += 1
            else:
                misses.append(f"{email['id']} {field}: expected {expected!r} got {actual!r}")
    total = len(emails) * len(FIELDS)
    correct = sum(hits.values())
    accuracy = correct / total
    with capsys.disabled():
        print(f"\nExtraction accuracy: {accuracy:.1%} ({correct}/{total})")
        for field in FIELDS:
            print(f"  {field:8} {hits[field]}/{len(emails)}")
        for line in misses:
            print(f"  miss: {line}")
    assert accuracy >= 0.85
    for field in FIELDS:
        assert hits[field] / len(emails) >= 0.80


def test_quote_with_shorthand_budget_is_a_lead():
    email = _by_id("m05")
    result = classify_rules(email)
    assert result.category == "lead"
    assert result.budget == "$6,000"
    assert result.intent == "request a proposal"
    assert result.name == "Tom Becker"
    assert "Tom" in result.draft_reply


def test_phishing_that_says_invoice_is_suspicious():
    result = classify_rules(_by_id("m35"))
    assert result.category == "suspicious"
    assert result.budget is None
    assert result.draft_reply.startswith("No reply")


def test_past_due_invoice_marked_urgent_stays_an_invoice():
    result = classify_rules(_by_id("m28"))
    assert result.category == "invoice"
    assert result.intent == "collect a payment"
    assert result.budget == "$2,000"


def test_broken_lead_form_is_support_not_a_sale():
    result = classify_rules(_by_id("m17"))
    assert result.category == "support"
    assert result.intent == "resolve a product issue"


def test_role_address_does_not_invent_a_person():
    result = classify_rules(_by_id("m23"))
    assert result.name is None
    assert result.company == "Brightline Dental"
    assert result.budget == "$2,400"


def test_confidence_is_bounded():
    for email in load_emails():
        result = classify_rules(email)
        assert 0 < result.confidence <= 0.97


def test_provider_defaults_to_rules(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert select_provider() == "rules"


def test_anthropic_key_wins_over_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test")
    assert select_provider() == "anthropic"


def test_llm_payload_maps_onto_a_classification():
    parsed = classification_from_payload(
        {
            "category": "lead",
            "confidence": 0.91,
            "name": "Jane Cole",
            "company": "Acme Robotics",
            "budget": "$8,000",
            "intent": "hire an automation freelancer",
            "draft_reply": "Hi Jane,\n\nThanks.",
        },
        model="anthropic",
    )
    assert parsed.category == "lead"
    assert parsed.model == "anthropic"
    assert parsed.company == "Acme Robotics"


def test_llm_payload_rejects_an_unknown_category():
    with pytest.raises(ValueError):
        classification_from_payload({"category": "newsletter", "confidence": 0.2}, model="openai")


def test_repository_does_not_name_the_retired_orchestrator():
    banned = "n" + "8n"
    root = Path(__file__).resolve().parents[1]
    skip = {".git", "node_modules", ".next", ".venv", ".pytest_cache", "__pycache__"}
    offenders = []
    for path in root.rglob("*"):
        if any(part in skip for part in path.parts):
            continue
        if banned in path.name.lower():
            offenders.append(str(path.relative_to(root)))
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if banned in text.lower():
            offenders.append(str(path.relative_to(root)))
    assert offenders == []


def _by_id(email_id: str) -> dict:
    return next(email for email in load_emails() if email["id"] == email_id)


def _same(actual, expected) -> bool:
    if actual is None or expected is None:
        return actual is None and expected is None
    return str(actual).casefold() == str(expected).casefold()
