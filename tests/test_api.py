"""Pipeline, CRM, and approval behavior against a throwaway mailbox."""

import pytest

from app.crm import active_adapters, highlevel_payload, hubspot_properties
from tests.conftest import signed_body


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
    payload = {
        "from_name": "Nina Shah",
        "from_email": "nina.shah@northwindlogistics.com",
        "subject": "Proposal for a classifier on our shared mailbox",
        "body": (
            "Hi Asad,\n\nWe are looking for a proposal. Budget is $9,000.\n\n"
            "Thanks,\nNina Shah\nDirector\nNorthwind Logistics\n"
            "nina.shah@northwindlogistics.com\n"
        ),
    }
    raw, headers = signed_body(payload)
    created = client.post("/api/webhooks/email", content=raw, headers=headers)
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


def test_desk_routes_require_a_bearer_token(client):
    denied = client.get("/api/triage", headers={"Authorization": "Bearer wrong"})
    assert denied.status_code == 401
    denied = client.get("/api/crm/leads", headers={"Authorization": "Bearer wrong"})
    assert denied.status_code == 401
    denied = client.post("/api/worker/run", headers={"Authorization": "Bearer wrong"})
    assert denied.status_code == 401
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/stats").status_code == 200
    for path in ("/api/intake/pending", "/api/stats", "/api/runs", "/api/worker"):
        assert client.get(path, headers={"Authorization": ""}).status_code == 401


def test_webhook_signature_and_idempotency(client):
    unsigned = client.post(
        "/api/webhooks/email",
        json={"from_email": "a@b.co", "subject": "Hi", "body": "Hello"},
    )
    assert unsigned.status_code == 401
    payload = {
        "from_email": "ada@example.com",
        "from_name": "Ada Lovelace",
        "subject": "Retainer",
        "body": "Budget is $4,000.\n\nThanks,\nAda Lovelace\nAnalytical Engines",
        "received_at": "2026-10-22T12:00:00+00:00",
    }
    raw, headers = signed_body(payload)
    first = client.post("/api/webhooks/email", content=raw, headers=headers)
    second = client.post("/api/webhooks/email", content=raw, headers=headers)
    assert first.status_code == 200
    assert first.json()["status"] == "queued"
    assert second.json()["status"] == "duplicate"
    assert second.json()["id"] == first.json()["id"]


def test_oversized_body_is_rejected(client):
    raw = b'{"subject":"s","body":"' + (b"x" * 300_000) + b'"}'
    response = client.post("/api/classify", content=raw, headers={"Content-Type": "application/json"})
    assert response.status_code == 413


def test_triage_list_is_a_preview_and_detail_is_full(client):
    payload = {
        "from_email": "ada@example.com",
        "from_name": "Ada Lovelace",
        "subject": "Long note",
        "body": "Budget is $4,000.\n" + ("detail " * 400) + "\nThanks,\nAda Lovelace\nAnalytical Engines",
        "received_at": "2026-10-22T12:00:00+00:00",
    }
    raw, headers = signed_body(payload)
    created = client.post("/api/webhooks/email", content=raw, headers=headers)
    assert created.status_code == 200
    client.post("/api/worker/run")
    listed = client.get("/api/triage?limit=50").json()["items"]
    match = next(item for item in listed if item["email_id"] == created.json()["id"])
    assert len(match["body"]) <= 500
    detail = client.get(f"/api/triage/{match['id']}").json()
    assert len(detail["body"]) > 500


def test_approval_locks_the_draft_and_does_not_alert_twice(client):
    jane = next(item for item in client.get("/api/triage").json()["items"] if item["email_id"] == "m01")
    assert client.post(f"/api/triage/{jane['id']}/approve").status_code == 200
    alerts = client.get("/api/alerts").json()["alerts"]
    again = client.post(f"/api/triage/{jane['id']}/approve")
    assert again.status_code == 409
    assert len(client.get("/api/alerts").json()["alerts"]) == len(alerts)
    edited = client.post(f"/api/triage/{jane['id']}/draft", json={"draft_reply": "Changed after approval."})
    assert edited.status_code == 409
    from app import db

    db.save_triage(
        "m01",
        {
            "category": "spam",
            "confidence": 0.4,
            "name": "Someone",
            "company": "Else",
            "budget": "$1",
            "intent": "nope",
            "draft_reply": "overwritten",
            "model": "rules",
        },
    )
    stored = db.get_triage(jane["id"])
    assert stored["draft_reply"] != "overwritten"
    assert stored["category"] != "spam"


def test_reset_is_refused_outside_demo_and_when_imap_is_set(client, monkeypatch):
    monkeypatch.setenv("IMAP_HOST", "imap.example.com")
    assert client.post("/api/demo/reset").status_code == 409
    monkeypatch.delenv("IMAP_HOST")
    monkeypatch.setenv("DEMO_MODE", "false")
    assert client.post("/api/demo/reset").status_code == 404


def test_worker_lock_skips_a_second_pass(client):
    from app import db

    assert db.acquire_worker_lock("held-by-test")
    body = client.post("/api/worker/run").json()
    assert body["skipped"] == "locked"
    db.release_worker_lock("held-by-test")


def test_cors_allows_the_desk_origin_only(client):
    ok = client.get("/api/health", headers={"Origin": "http://127.0.0.1:8742"})
    assert ok.headers.get("access-control-allow-origin") == "http://127.0.0.1:8742"
    blocked = client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert blocked.headers.get("access-control-allow-origin") is None
    preflight = client.options(
        "/api/triage",
        headers={
            "Origin": "http://127.0.0.1:8742",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers.get("access-control-allow-origin") == "http://127.0.0.1:8742"


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


def test_remote_crm_upserts_and_records_failures(client, monkeypatch):
    import httpx

    from app.crm import store_lead

    calls: list[str] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(url)
        request = httpx.Request("POST", url)
        return httpx.Response(500, json={"ok": False}, request=request)

    monkeypatch.setenv("HUBSPOT_TOKEN", "pat-test")
    monkeypatch.setattr(httpx, "post", fake_post)
    failed = store_lead(
        {
            "email_id": "remote-1",
            "name": "Ada Lovelace",
            "company": "Analytical Engines",
            "email": "ada@example.com",
            "budget": "$4,000",
            "intent": "request a proposal",
            "category": "lead",
            "source_subject": "Retainer",
            "status": "Reply pending",
        }
    )
    assert calls[0].endswith("/crm/v3/objects/contacts/batch/upsert")
    assert len(calls) == 2
    assert failed["remote_status"] == "error"
    assert "500" in failed["remote_error"]

    calls.clear()
    skipped = store_lead(
        {
            "email_id": "remote-2",
            "name": None,
            "email": "",
            "category": "lead",
            "status": "Reply pending",
        }
    )
    assert calls == []
    assert skipped["remote_status"] == "skipped"
    assert skipped["remote_error"] == "no email"

    def ok_post(url, headers=None, json=None, timeout=None):
        calls.append(url)
        request = httpx.Request("POST", url)
        return httpx.Response(200, json={"ok": True}, request=request)

    monkeypatch.delenv("HUBSPOT_TOKEN")
    monkeypatch.setenv("GHL_API_KEY", "ghl-test")
    monkeypatch.setenv("GHL_LOCATION_ID", "loc-1")
    monkeypatch.setattr(httpx, "post", ok_post)
    stored = store_lead(
        {
            "email_id": "remote-3",
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "category": "lead",
            "status": "Reply pending",
        }
    )
    assert calls == ["https://services.leadconnectorhq.com/contacts/upsert"]
    assert stored["remote_status"] == "ok"


def test_slack_text_is_escaped_and_failures_are_recorded(client, monkeypatch):
    import httpx

    from app.alerts import post_alert, render_alert

    title, body = render_alert(
        "lead",
        {"name": "A & B <script>", "company": "Co", "budget": "$1", "intent": "hire", "subject": "Hi"},
    )
    assert "&amp;" in body
    assert "&lt;" in body
    assert "<script>" not in body

    def fail(url, json=None, timeout=None):
        request = httpx.Request("POST", url)
        return httpx.Response(500, json={"ok": False}, request=request)

    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example/slack")
    monkeypatch.setattr(httpx, "post", fail)
    stored = post_alert("lead", {"email_id": "m01", "name": "Jane", "subject": "Hi"})
    assert stored["delivered"] is False
    assert stored["delivery_error"] == "HTTP 500"
    titled = post_alert("lead", {"email_id": "m01", "name": "Jane"}, title="<!channel> wire now")
    assert "<!channel>" not in titled["title"]
    assert "&lt;!channel&gt;" in titled["title"]


def test_triage_rejects_a_bad_category_and_an_approved_overwrite(client):
    jane = next(item for item in client.get("/api/triage").json()["items"] if item["email_id"] == "m01")
    rejected = client.post(
        "/api/triage",
        json={
            "email_id": "m01",
            "category": "pwned",
            "confidence": 99,
            "intent": "nope",
            "draft_reply": "hi",
        },
    )
    assert rejected.status_code == 422
    assert client.post(f"/api/triage/{jane['id']}/approve").status_code == 200
    overwrite = client.post(
        "/api/triage",
        json={
            "email_id": "m01",
            "category": "spam",
            "confidence": 0.2,
            "intent": "nope",
            "draft_reply": "changed",
        },
    )
    assert overwrite.status_code == 409


def test_production_mode_refuses_the_sample_secrets(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("API_TOKEN", "lane-demo-token")
    monkeypatch.setenv("WEBHOOK_SECRET", "lane-demo-webhook")
    from app.main import assert_runtime_secrets

    with pytest.raises(RuntimeError):
        assert_runtime_secrets()


def test_hubspot_note_is_associated_to_the_contact(monkeypatch):
    import httpx

    from app.crm import _hubspot_note

    seen: dict = {}

    def fake_get(url, headers=None, params=None, timeout=None):
        request = httpx.Request("GET", url)
        return httpx.Response(200, json={"id": "99"}, request=request)

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["payload"] = json
        request = httpx.Request("POST", url)
        return httpx.Response(201, json={"id": "note-1"}, request=request)

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "post", fake_post)
    _hubspot_note("pat-test", "ada@example.com", {"budget": "$4,000", "intent": "hire"})
    association = seen["payload"]["associations"][0]
    assert association["to"]["id"] == "99"
    assert association["types"][0]["associationTypeId"] == 202
    assert "$4,000" in seen["payload"]["properties"]["hs_note_body"]


def test_accept_moves_a_review_to_the_suggested_label(client):
    from app import db

    vague = {
        "id": "review-me",
        "from_name": "Imani Cole",
        "from_email": "imani@colelogistics.com",
        "subject": "got a minute?",
        "body": "Around forty two hundred dollars for the Salesforce import.",
        "received_at": "2026-10-22T00:00:00+00:00",
    }
    db.insert_email(vague)
    stored = db.save_triage(
        vague["id"],
        {
            "category": "review",
            "confidence": 0.42,
            "name": "Imani Cole",
            "company": "Cole Logistics",
            "budget": "$4,200",
            "intent": "request a proposal",
            "draft_reply": "Needs review.",
            "model": "rules",
            "suggested_category": "lead",
            "suggestion_confidence": 0.66,
            "reasons": ["a price is written in the message"],
        },
    )
    response = client.post(f"/api/triage/{stored['id']}/accept", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["category"] == "lead"
    leads = client.get("/api/crm/leads").json()["leads"]
    assert any(lead["email"] == "imani@colelogistics.com" for lead in leads)
