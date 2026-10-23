"""Round-12 structure. The measurement set is not a tuning set."""

import json
import re
import subprocess
from pathlib import Path

from app.budget import extract_budget
from app.classifier import classify_rules
from app.gate import evaluate_filing

ROOT = Path(__file__).resolve().parents[1]
HELD = json.loads((ROOT / "data" / "hand_heldout_r12.json").read_text(encoding="utf-8"))


def _mail(row: dict) -> dict:
    return {
        "from_name": row["from_name"],
        "from_email": row["from_email"],
        "subject": row["subject"],
        "body": row["body"],
    }


def _result(row: dict):
    contacts = None if row.get("stateless") else row.get("contacts") or None
    return classify_rules(_mail(row), contacts)


def test_number_words_keep_the_written_currency():
    assert extract_budget("twelve thousand euros") == "€12,000"
    assert extract_budget("El presupuesto es doce mil euros.") == "€12,000"
    assert extract_budget("Le montant prévu est douze mille euros.") == "€12,000"
    assert extract_budget("O valor previsto é doze mil euros.") == "€12,000"
    assert extract_budget("Das Budget beträgt zwanzigtausend Euro.") == "€20,000"
    assert extract_budget("Tenemos tres mil seiscientos euros disponibles.") == "€3,600"
    assert extract_budget("The package for this seat is ninety thousand dollars a year.") == "$90,000"


def test_lookalike_and_child_pay_links_are_suspicious_without_contacts():
    for row in HELD:
        if row["bucket"] != "phish" or not row["stateless"]:
            continue
        result = classify_rules(_mail(row), None)
        assert result.category == "suspicious", row["id"]
        assert "urgent" not in result.secondary_categories
        assert "deceptive_link" in result.risk_flags


def test_contact_child_and_lookalike_are_suspicious_on_the_worker_path():
    for row in HELD:
        if row["bucket"] != "phish" or row["stateless"]:
            continue
        result = classify_rules(_mail(row), row["contacts"])
        assert result.category == "suspicious", row["id"]
        assert "deceptive_link" in result.risk_flags


def test_confirm_cannot_file_a_pay_link_the_crm_route_rejects(client):
    from app import db

    for row in HELD:
        if row["bucket"] != "phish":
            continue
        email_id = f"r12-{row['id']}"
        db.insert_email({**_mail(row), "id": email_id, "received_at": "2026-10-22T00:00:00+00:00"})
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
        if row["contacts"]:
            db.insert_email(
                {
                    "id": f"known-{row['id']}",
                    "from_name": row["contacts"][0]["name"],
                    "from_email": row["contacts"][0]["email"],
                    "subject": "Earlier note",
                    "body": "A previous note from this sender.\n",
                    "received_at": "2026-10-21T00:00:00+00:00",
                }
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


def test_own_domain_overdue_invoice_stays_an_invoice():
    overdue = next(row for row in HELD if row["id"] == "r16")
    calm = next(row for row in HELD if row["id"] == "r17")
    overdue_result = _result(overdue)
    calm_result = _result(calm)
    assert overdue_result.category == "invoice"
    assert overdue_result.category != "suspicious"
    assert "urgent" in overdue_result.secondary_categories
    assert "deceptive_link" not in overdue_result.risk_flags
    assert calm_result.category == "invoice"
    assert "urgent" not in calm_result.secondary_categories
    assert calm_result.category != "suspicious"


def test_measurement_set_fields_and_refusal():
    phish = [row for row in HELD if row["bucket"] == "phish"]
    leads = [row for row in HELD if row["bucket"] == "lead"]
    caught = 0
    refused = 0
    category_hit = company_hit = budget_hit = 0
    for row in phish:
        result = _result(row)
        if result.category == "suspicious":
            caught += 1
        decision = evaluate_filing(
            _mail(row),
            current_category="lead",
            target="lead",
            known_contacts=row["contacts"],
            confirmed=True,
        )
        if not decision.allow:
            refused += 1
    for row in leads:
        result = _result(row)
        if result.category == row["category"]:
            category_hit += 1
        if result.company == row["company"]:
            company_hit += 1
        if result.budget == row["budget"]:
            budget_hit += 1
        else:
            raise AssertionError(f"{row['id']} budget {result.budget!r} != {row['budget']!r} company {result.company!r} category {result.category}")
    assert caught == len(phish)
    assert refused == len(phish)
    assert category_hit == len(leads)
    assert company_hit == len(leads)
    assert budget_hit == len(leads)


def test_dead_keyword_helpers_are_gone():
    import app.classifier as classifier

    assert not hasattr(classifier, "is_outage")
    assert not hasattr(classifier, "has_operational_pressure")


def test_measurement_set_is_paraphrase_disjoint_and_predates_the_weight_stamp():
    from app.corpus import rows

    def grams(text: str, size: int) -> set[tuple[str, ...]]:
        words = re.findall(r"\w+", text.lower(), flags=re.UNICODE)
        return {tuple(words[index : index + size]) for index in range(max(0, len(words) - size + 1))}

    corpus = set()
    blob = []
    for item in rows():
        blob.append(item["text"])
        corpus |= grams(item["text"], 6)
    joined = "\n".join(blob)
    for row in HELD:
        assert row["body"].strip() not in joined
        assert not (grams(row["body"], 6) & corpus)

    intro = subprocess.check_output(
        ["git", "log", "--diff-filter=A", "--format=%H", "--", "data/hand_heldout_r12.json"],
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
    assert names == ["data/hand_heldout_r12.json"]
    weights = subprocess.check_output(
        ["git", "log", "-1", "--format=%H", "--", "app/model_weights.json"],
        cwd=ROOT,
        text=True,
    ).strip()
    subprocess.check_call(["git", "merge-base", "--is-ancestor", intro, weights], cwd=ROOT)
    assert intro != weights
