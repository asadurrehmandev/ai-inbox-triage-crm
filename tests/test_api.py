"""Pipeline, CRM, and approval behavior against a throwaway mailbox."""

import pytest
from fastapi.testclient import TestClient

from app.crm import active_adapters, highlevel_payload, hubspot_properties


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "triage.db"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("HUBSPOT_TOKEN", raising=False)
    monkeypatch.delenv("GHL_API_KEY", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("WORKER_ENABLED", "false")
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_health_reports_demo_mode(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["mode"] == "rules"
    assert body["mailbox"] == "mock-imap"
    assert body["crm"] == "mock"
    assert body["worker"]["engine"] == "apscheduler"
    assert body["worker"]["enabled"] is False


def test_seed_leaves_a_waiting_queue_and_files_known_leads(client):
    stats = client.get("/api/stats").json()
    assert stats["waiting"] == 8
    assert stats["processed"] >= 30
    assert stats["leads"] >= 8
    assert stats["hours_saved"] > 0
    lead_ids = {lead["email_id"] for lead in client.get("/api/crm/leads").json()["leads"]}
    assert "m01" in lead_ids
    assert "m32" not in lead_ids
    assert "m13" not in lead_ids


def test_intake_run_qualifies_a_lead_and_drops_spam(client):
    response = client.post("/api/intake/run")
    assert response.status_code == 200
    assert response.json()["processed"] == 8
    lead_ids = {lead["email_id"] for lead in client.get("/api/crm/leads").json()["leads"]}
    assert "m02" in lead_ids
    assert "m06" in lead_ids
    assert "m08" in lead_ids
    assert "m32" not in lead_ids
    assert "m23" not in lead_ids
    alert_ids = {alert["email_id"] for alert in client.get("/api/alerts").json()["alerts"]}
    assert "m32" not in alert_ids
    assert "m39" in alert_ids
    assert client.get("/api/stats").json()["waiting"] == 0


def test_approve_keeps_edits_and_updates_the_lead(client):
    jane = next(item for item in client.get("/api/triage").json()["items"] if item["email_id"] == "m01")
    edited = client.post(
        f"/api/triage/{jane['id']}/draft",
        json={"draft_reply": "Hi Jane,\n\nI can start Monday."},
    )
    assert edited.status_code == 200
    assert edited.json()["edited"] is True
    approved = client.post(f"/api/triage/{jane['id']}/approve")
    assert approved.status_code == 200
    body = approved.json()
    assert body["approved"] is True
    assert "Monday" in body["draft_reply"]
    lead = next(item for item in client.get("/api/crm/leads").json()["leads"] if item["email_id"] == "m01")
    assert lead["status"] == "Reply approved"
    titles = [alert["title"] for alert in client.get("/api/alerts").json()["alerts"]]
    assert "Reply approved" in titles


def test_classify_endpoint_is_stateless(client):
    response = client.post(
        "/api/classify",
        json={
            "email_id": "ad-hoc",
            "from_name": "Jane Cole",
            "from_email": "jane.cole@acmerobotics.com",
            "subject": "Looking for a Python partner for a monthly retainer",
            "body": "We are looking for a freelancer. Budget is $8,000/mo.\n\nThanks,\nJane Cole\nOperations Director\nAcme Robotics\n",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["category"] == "lead"
    assert body["budget"] == "$8,000"
    assert body["model"] == "rules"


def test_webhook_is_classified_when_the_worker_runs(client):
    created = client.post(
        "/api/webhooks/email",
        json={
            "from_name": "Nina Shah",
            "from_email": "nina.shah@northwindlogistics.com",
            "subject": "Proposal for a classifier on our shared mailbox",
            "body": (
                "Hi Asad,\n\nWe are looking for a proposal. Budget is $9,000.\n\n"
                "Thanks,\nNina Shah\nDirector\nNorthwind Logistics\n"
                "nina.shah@northwindlogistics.com\n"
            ),
        },
    )
    assert created.status_code == 200
    assert created.json()["status"] == "queued"
    assert client.get("/api/stats").json()["waiting"] == 9
    run = client.post("/api/worker/run")
    assert run.status_code == 200
    assert run.json()["processed"] == 9
    assert run.json()["source"] == "manual"
    leads = client.get("/api/crm/leads").json()["leads"]
    match = next(lead for lead in leads if lead["email"] == "nina.shah@northwindlogistics.com")
    assert match["destination"].startswith("mock")
    assert match["budget"] == "$9,000"
    assert client.get("/api/stats").json()["waiting"] == 0


def test_adapter_list_starts_with_the_mock_crm(monkeypatch):
    monkeypatch.delenv("HUBSPOT_TOKEN", raising=False)
    monkeypatch.delenv("GHL_API_KEY", raising=False)
    monkeypatch.delenv("GHL_LOCATION_ID", raising=False)
    assert [adapter.name for adapter in active_adapters()] == ["mock"]
    monkeypatch.setenv("HUBSPOT_TOKEN", "pat-test")
    assert [adapter.name for adapter in active_adapters()] == ["mock", "hubspot"]


def test_crm_payloads_match_hubspot_and_gohighlevel():
    lead = {
        "name": "Jane Cole",
        "email": "jane.cole@acmerobotics.com",
        "company": "Acme Robotics",
        "category": "lead",
    }
    hubspot = hubspot_properties(lead)
    assert hubspot["firstname"] == "Jane"
    assert hubspot["lastname"] == "Cole"
    assert hubspot["company"] == "Acme Robotics"
    assert hubspot["lifecyclestage"] == "lead"
    highlevel = highlevel_payload(lead)
    assert highlevel["companyName"] == "Acme Robotics"
    assert highlevel["source"] == "Lane inbox triage"
    assert "lane" in highlevel["tags"]
