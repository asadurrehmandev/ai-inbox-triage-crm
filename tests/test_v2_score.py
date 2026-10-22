"""The v2 mailbox is scored, not used as a word list.

Security invariants are asserted. Category accuracy is printed and is not a gate.
"""

from app.classifier import classify_rules
from app.pipeline import apply_policy
from app import db
from tests.new_emails_v2 import EMAILS
from tests.score_v2 import main


def test_v2_security_invariants(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "triage.db"))
    db.init_db()
    flagged = 0
    must = [email for email in EMAILS if email.get("must_flag")]
    for email in must:
        result = classify_rules(email)
        assert result.category == "suspicious", email["id"]
        assert result.budget is None, email["id"]
        assert "confirm payment" not in result.draft_reply.lower()
        row = {**email, "id": email["id"], "received_at": "2026-10-22T00:00:00+00:00"}
        db.insert_email(row)
        outcome = apply_policy(row, result)
        assert outcome["lead"] is None
        flagged += 1
    assert flagged == len(must) == 9
    for email in EMAILS:
        if email["id"] in {"n50", "n51"}:
            result = classify_rules(email)
            assert result.category != "suspicious", email["id"]
            assert result.budget is not None
    with capsys.disabled():
        main(["score_v2.py", "http://unused", "token", "/tmp/v2-score.json", "--direct"])
