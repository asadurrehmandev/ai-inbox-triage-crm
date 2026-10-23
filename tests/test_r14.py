"""Round-14 structure. The measurement set was hashed before these rules."""

import hashlib
import json
import re
import subprocess
from pathlib import Path

from app.classifier import classify_rules, is_person
from app.gate import evaluate_filing
from app.risk import hard_flags, payment_related

ROOT = Path(__file__).resolve().parents[1]
HELD = json.loads((ROOT / "data" / "hand_heldout_r14.json").read_text(encoding="utf-8"))
_WRITTEN = {"kronor", "francs", "forints", "rand"}


def _mail(row: dict) -> dict:
    return {
        "from_name": row["from_name"],
        "from_email": row["from_email"],
        "subject": row["subject"],
        "body": row["body"],
    }


def _result(row: dict):
    return classify_rules(_mail(row), row.get("contacts") or None)


def _save(db, row: dict, email_id: str, category: str) -> dict:
    db.insert_email({**_mail(row), "id": email_id, "received_at": "2026-10-23T00:00:00+00:00"})
    db.save_triage(
        email_id,
        {
            "category": category,
            "confidence": 0.8,
            "name": row["from_name"],
            "company": row.get("company") or "Held",
            "budget": row.get("budget"),
            "intent": "held measurement",
            "draft_reply": "Holding this.",
            "model": "rules",
            "risk_flags": [],
            "suggested_category": category,
            "suggestion_confidence": 0.8,
            "reasons": [],
        },
    )
    return db.get_triage_by_email(email_id)


def test_measurement_file_matches_its_hash_and_was_committed_alone():
    raw = (ROOT / "data" / "hand_heldout_r14.json").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    recorded = (ROOT / "data" / "hand_heldout_r14.sha256").read_text(encoding="utf-8").split()[0]
    assert digest == recorded
    assert len(HELD) >= 40
    intro = subprocess.check_output(
        ["git", "log", "--diff-filter=A", "--format=%H", "--", "data/hand_heldout_r14.json"],
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
    assert names == ["data/hand_heldout_r14.json", "data/hand_heldout_r14.sha256"]
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
    for path in (
        "data/hand_heldout.json",
        "data/hand_heldout_r12.json",
        "data/hand_heldout_r13.json",
    ):
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


def test_payment_and_phishing_cannot_be_confirmed(client):
    from app import db

    blocked = [row for row in HELD if row["crm"] == "refuse"]
    assert blocked
    for row in blocked:
        email_id = f"r14-{row['id']}"
        stored = _save(db, row, email_id, "lead")
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


def test_ordinary_budget_links_confirm_and_display_name_confirms(client):
    from app import db

    soft = [row for row in HELD if row["bucket"] == "lead" and row["crm"] == "allow_confirm"]
    assert len(soft) >= 8
    filed = 0
    for row in soft:
        result = _result(row)
        assert result.category == "lead", row["id"]
        assert result.category != "suspicious", row["id"]
        email_id = f"r14-{row['id']}"
        stored = _save(db, row, email_id, result.category)
        direct = client.post(
            "/api/crm/leads",
            json={
                "email_id": email_id,
                "name": row["from_name"],
                "from_email": row["from_email"],
                "category": "lead",
                "company": row["company"],
                "budget": row["budget"],
                "intent": "a quote",
            },
        )
        accept = client.post(
            f"/api/triage/{stored['id']}/accept",
            json={"category": "lead", "confirm": True},
        )
        assert direct.status_code == 409, row["id"]
        assert accept.status_code == 200, row["id"]
        filed += 1
    assert filed == len(soft)

    for row in HELD:
        if row["bucket"] != "confirmable":
            continue
        result = _result(row)
        assert result.category == "lead", row["id"]
        assert "display_name_mismatch" in result.risk_flags, row["id"]
        assert "display_name_mismatch" not in hard_flags(result.risk_flags), row["id"]
        contact = row["contacts"][0]
        db.upsert_lead(
            {
                "email_id": f"seed-{row['id']}",
                "name": contact["name"],
                "email": contact["email"],
                "company": contact.get("company"),
                "intent": "known contact",
                "category": "lead",
                "source_subject": "Known",
            }
        )
        email_id = f"r14-{row['id']}"
        stored = _save(db, row, email_id, result.category)
        direct = client.post(
            "/api/crm/leads",
            json={
                "email_id": email_id,
                "name": row["from_name"],
                "from_email": row["from_email"],
                "category": "lead",
                "company": row["company"],
                "budget": row["budget"],
                "intent": "a quote",
            },
        )
        accept = client.post(
            f"/api/triage/{stored['id']}/accept",
            json={"category": "lead", "confirm": True},
        )
        assert direct.status_code == 409, row["id"]
        assert accept.status_code == 200, row["id"]


def test_heldout_labels_currency_and_company():
    phish = [row for row in HELD if row["bucket"] == "phish"]
    leads = [row for row in HELD if row["bucket"] == "lead"]
    urgent = [row for row in HELD if row["category"] == "urgent"]
    assert len(phish) >= 8
    assert len(leads) >= 16
    caught = 0
    false_urgent = []
    urgent_hit = 0
    category_hit = budget_hit = 0
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
        if row["bucket"] == "lead":
            category_hit += result.category == "lead"
            budget_hit += result.budget == row["budget"]
            assert result.name == row["name"], (row["id"], result.name, row["name"])
            assert result.company == row["company"], (row["id"], result.company, row["company"])
            if row["company"]:
                assert "[truncated]" not in result.company.casefold()
        if row["budget"] and row["budget"].split()[0] in _WRITTEN:
            assert result.budget == row["budget"], row["id"]
            assert not str(result.budget).startswith("$"), row["id"]
        if row["id"] == "k23":
            assert result.name != "Larkspur GmbH"
            assert is_person("Larkspur GmbH") is False
        if row["id"] == "k24":
            assert result.name is None
            assert is_person("Northglass Ltd") is False
        if row["id"] == "k41":
            assert result.category == "invoice"
            assert "urgent" not in result.secondary_categories
            assert result.category != "suspicious"
    assert caught == len(phish)
    assert urgent_hit == len(urgent)
    assert len(false_urgent) <= 1, false_urgent
    assert category_hit >= 14
    assert budget_hit == len(leads)
