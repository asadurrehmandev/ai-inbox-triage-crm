"""Phishing, fraud, and injection run before a category is trusted."""

import json
from pathlib import Path

from app.classifier import classify_rules
from app.pipeline import accept_suggestion, apply_policy
from app import db

HELD = {
    row["id"]: row
    for row in json.loads(
        (Path(__file__).resolve().parents[1] / "data" / "eval_unseen.json").read_text(encoding="utf-8")
    )
}


def _mail(email_id: str) -> dict:
    return HELD[email_id]


def test_phishing_and_injection_are_suspicious_and_not_filed(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "triage.db"))
    db.init_db()
    for email_id in ("q07", "q18", "q29", "q36"):
        email = _mail(email_id)
        result = classify_rules(email)
        assert result.category == "suspicious", email_id
        assert result.budget is None
        assert result.draft_reply.startswith("No reply")
        assert "confirm payment" not in result.draft_reply.lower()
        db.insert_email({**email, "id": email_id, "received_at": "2026-10-22T00:00:00+00:00"})
        outcome = apply_policy({**email, "id": email_id}, result)
        assert outcome["lead"] is None
        assert outcome["alert"]["title"].startswith("Possible phishing")
    assert db.list_leads() == []


def test_urgent_needs_a_known_sender_or_a_thread():
    # A first contact is not urgent, even when the outage or the deadline is real.
    for email_id in ("q14", "q15", "q19", "q27"):
        result = classify_rules(_mail(email_id))
        assert result.category != "urgent", email_id
        assert result.suggested_category == "urgent", email_id
    hidden = classify_rules(_mail("q19"))
    assert "instruction_suppression" in hidden.risk_flags
    assert hidden.category != "urgent"
    # The same outage is urgent once the sender is already known, and the
    # suppression note still does not hide it.
    known = classify_rules(_mail("q19"), [{"name": "Hannah Weiss", "email": "hannah@weissdental.com"}])
    assert known.category == "urgent"
    assert "instruction_suppression" in known.risk_flags
    reply = dict(_mail("q14"))
    reply["subject"] = "Re: checkout throwing 502s"
    assert classify_rules(reply).category == "urgent"


def test_non_leads_do_not_look_like_sales():
    cold = classify_rules(_mail("q10"))
    assert cold.category == "spam"
    assert cold.name is None
    assert cold.budget is None

    ooo = classify_rules(_mail("q31"))
    assert ooo.category in {"spam", "support"}
    assert ooo.name is None

    trial = classify_rules(_mail("q33"))
    assert trial.category != "lead"
    assert trial.budget is None

    refund = classify_rules(_mail("q35"))
    assert refund.category == "invoice"
    assert refund.budget == "$1,800"


def test_forwarded_mail_uses_the_inner_sender():
    result = classify_rules(_mail("q09"))
    assert result.category == "lead"
    assert result.name == "Kevin Ortiz"
    assert result.contact_email == "kevin@ortizlaw.com"
    assert result.forwarded_by == "sam@lane.studio"
    assert result.budget == "$7,500"


def test_a_support_note_with_a_quote_still_opens_a_lead(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "triage.db"))
    db.init_db()
    email = {**_mail("q13"), "id": "q13", "received_at": "2026-10-22T00:00:00+00:00"}
    db.insert_email(email)
    result = classify_rules(email)
    assert "lead" in {result.category, *result.secondary_categories}
    assert "support" in {result.category, *result.secondary_categories}
    outcome = apply_policy(email, result)
    assert outcome["lead"] is None
    filed = accept_suggestion(db.get_triage(outcome["triage"]["id"]), "lead")
    assert filed["lead"] is not None
    assert filed["lead"]["budget"] == "$3,000"
    assert filed["lead"]["email"] == "ben@ashfordfitness.com"


def test_bare_server_error_without_customer_impact_stays_support():
    result = classify_rules(_mail("h31"))
    assert result.category == "support"
