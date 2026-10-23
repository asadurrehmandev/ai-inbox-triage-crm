"""Round-13 structure. The measurement set was hashed before these rules."""

import hashlib
import json
import re
import subprocess
from pathlib import Path

from app.classifier import classify_rules
from app.gate import evaluate_filing
from app.risk import payment_related

ROOT = Path(__file__).resolve().parents[1]
HELD = json.loads((ROOT / "data" / "hand_heldout_r13.json").read_text(encoding="utf-8"))


def _mail(row: dict) -> dict:
    return {
        "from_name": row["from_name"],
        "from_email": row["from_email"],
        "subject": row["subject"],
        "body": row["body"],
    }


def _result(row: dict):
    return classify_rules(_mail(row), None)


def test_measurement_file_matches_its_hash_and_was_committed_alone():
    raw = (ROOT / "data" / "hand_heldout_r13.json").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    recorded = (ROOT / "data" / "hand_heldout_r13.sha256").read_text(encoding="utf-8").split()[0]
    assert digest == recorded
    assert len(HELD) >= 40
    intro = subprocess.check_output(
        ["git", "log", "--diff-filter=A", "--format=%H", "--", "data/hand_heldout_r13.json"],
        cwd=ROOT,
        text=True,
    ).splitlines()[0]
    names = [
        line
        for line in subprocess.check_output(
            ["git", "show", "--name-only", "--format=", intro],
            cwd=ROOT,
            text=True,
        ).splitlines()
        if line.strip()
    ]
    assert names == ["data/hand_heldout_r13.json", "data/hand_heldout_r13.sha256"]
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", intro, "HEAD", "--", "app/model_weights.json", "app/encoder_delta.npz"],
        cwd=ROOT,
        text=True,
    ).strip()
    assert changed == ""


def test_measurement_set_is_paraphrase_disjoint():
    from app.corpus import rows

    def grams(text: str, size: int = 6) -> set[tuple[str, ...]]:
        words = re.findall(r"\w+", text.lower(), flags=re.UNICODE)
        return {tuple(words[index : index + size]) for index in range(max(0, len(words) - size + 1))}

    corpus = set()
    blob = []
    for item in rows():
        blob.append(item["text"])
        corpus |= grams(item["text"])
    for path in ("data/hand_heldout.json", "data/hand_heldout_r12.json"):
        previous = json.loads((ROOT / path).read_text(encoding="utf-8"))
        for item in previous:
            body = item["body"] if isinstance(item, dict) else ""
            blob.append(body)
            corpus |= grams(body)
    joined = "\n".join(blob)
    banned = (
        "Neue Bankverbindung",
        "künftige Zahlungen",
        "Acil değil",
        "fora do ar",
        "çalışmıyor",
        "8 万元",
        "15,000 درهم",
    )
    for row in HELD:
        assert row["body"].strip() not in joined
        assert not (grams(row["body"]) & corpus)
        for phrase in banned:
            assert phrase not in row["body"]


def test_payment_lures_and_bank_details_are_not_filed(client):
    from app import db

    lures = [row for row in HELD if row["crm"] == "refuse"]
    assert lures
    for row in lures:
        email_id = f"r13-{row['id']}"
        db.insert_email({**_mail(row), "id": email_id, "received_at": "2026-10-23T00:00:00+00:00"})
        db.save_triage(
            email_id,
            {
                "category": "lead",
                "confidence": 0.9,
                "name": row["from_name"],
                "company": "Forced",
                "budget": "$1",
                "intent": "forced label",
                "draft_reply": "Holding this.",
                "model": "rules",
                "risk_flags": [],
                "suggested_category": "lead",
                "suggestion_confidence": 0.9,
                "reasons": [],
            },
        )
        stored = db.get_triage_by_email(email_id)
        accept = client.post(
            f"/api/triage/{stored['id']}/accept",
            json={"category": "lead", "confirm": True},
        )
        direct = client.post(
            "/api/crm/leads",
            json={
                "email_id": email_id,
                "name": row["from_name"],
                "from_email": row["from_email"],
                "category": "lead",
                "company": "Forced",
                "budget": "$1",
                "intent": "forced label",
            },
        )
        assert accept.status_code == 409, row["id"]
        assert direct.status_code == 409, row["id"]
        assert email_id not in {lead["email_id"] for lead in db.list_leads()}


def test_ordinary_unknown_domain_and_shortener_can_be_confirmed(client):
    from app import db

    for row in HELD:
        if row["crm"] != "allow_confirm":
            continue
        email_id = f"r13-{row['id']}"
        db.insert_email({**_mail(row), "id": email_id, "received_at": "2026-10-23T00:00:00+00:00"})
        db.save_triage(
            email_id,
            {
                "category": "lead",
                "confidence": 0.7,
                "name": row["from_name"],
                "company": "Orchard",
                "budget": None,
                "intent": "a sketch",
                "draft_reply": "Holding this.",
                "model": "rules",
                "risk_flags": [],
                "suggested_category": "review",
                "suggestion_confidence": 0.4,
                "reasons": [],
            },
        )
        stored = db.get_triage_by_email(email_id)
        direct = client.post(
            "/api/crm/leads",
            json={
                "email_id": email_id,
                "name": row["from_name"],
                "from_email": row["from_email"],
                "category": "lead",
                "company": "Orchard",
                "budget": None,
                "intent": "a sketch",
            },
        )
        accept = client.post(
            f"/api/triage/{stored['id']}/accept",
            json={"category": "lead", "confirm": True},
        )
        assert direct.status_code == 409, row["id"]
        assert accept.status_code == 200, row["id"]


def test_heldout_labels_and_lead_fields():
    phish = [row for row in HELD if row["bucket"] == "phish"]
    leads = [row for row in HELD if row["bucket"] == "lead"]
    urgent = [row for row in HELD if row["category"] == "urgent"]
    caught = 0
    false_urgent = []
    urgent_hit = 0
    for row in HELD:
        result = _result(row)
        if row["bucket"] == "phish" and result.category == "suspicious" and "urgent" not in result.secondary_categories:
            caught += 1
        if row["category"] != "urgent" and result.category == "urgent":
            false_urgent.append(row["id"])
        if row["category"] == "urgent" and result.category == "urgent":
            urgent_hit += 1
        if row["bucket"] == "support":
            assert result.category == "support", row["id"]
            assert "urgent" not in result.secondary_categories
        if row["bucket"] == "payment":
            assert payment_related(f"{row['subject']}\n{row['body']}"), row["id"]
            decision = evaluate_filing(_mail(row), current_category="lead", target="lead", confirmed=True)
            assert not decision.allow, row["id"]
        if row["id"] == "h44":
            assert result.category == "invoice"
            assert "urgent" in result.secondary_categories
        if row["id"] == "h45":
            assert result.category == "invoice"
            assert "urgent" not in result.secondary_categories
            assert result.category != "suspicious"
        if row["id"] == "h48":
            assert result.category == "recruiter"
            assert result.budget is None
    category_hit = company_hit = budget_hit = name_hit = 0
    for row in leads:
        result = _result(row)
        category_hit += result.category == "lead"
        company_hit += result.company == row["company"]
        budget_hit += result.budget == row["budget"]
        name_hit += result.name == row["name"]
    assert caught == len(phish)
    assert len(phish) >= 13
    assert urgent_hit == len(urgent)
    assert len(false_urgent) <= 1
    assert len(leads) >= 15
    assert category_hit >= 13
    assert category_hit == len(leads)
    assert company_hit == len(leads)
    assert budget_hit == len(leads)
    assert name_hit == len(leads)
