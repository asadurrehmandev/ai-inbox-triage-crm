"""The v3 mailbox is an outside set. Security is asserted. Accuracy is printed."""

from app.classifier import classify_rules
from app.pipeline import apply_policy
from app import db
from tests.new_emails_v3 import EMAILS
from tests.score_v3 import main


def test_v3_attacks_do_not_reach_the_crm(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "triage.db"))
    db.init_db()
    must = [email for email in EMAILS if email.get("must_flag")]
    for email in must:
        result = classify_rules(email)
        assert result.category == "suspicious", (email["id"], result.category, result.risk_flags)
        assert result.category != "urgent"
        assert result.budget is None, email["id"]
        row = {**email, "received_at": "2026-10-22T00:00:00+00:00"}
        db.insert_email(row)
        outcome = apply_policy(row, result)
        assert outcome["lead"] is None, email["id"]
        assert outcome["alert"]["category"] != "urgent"
    # A real project that mentions IBAN, a typo correction, and a vendor receipt stay clean.
    for email_id in ("v01", "v36", "v37", "v39"):
        result = classify_rules(next(email for email in EMAILS if email["id"] == email_id))
        assert result.category != "suspicious", email_id
    with capsys.disabled():
        main(["score_v3.py", "http://unused", "token", "/tmp/v3-score.json", "--direct"])
