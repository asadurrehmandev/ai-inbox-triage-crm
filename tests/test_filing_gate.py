"""Server filing gate. These fixtures are original. They are not a sealed QA set."""

import json

from app import crm, db
from app.classifier import Classification
from app.risk import payment_related


def _crm_ids(client) -> set[str]:
    return {lead["email_id"] for lead in client.get("/api/crm/leads").json()["leads"]}


def _park(email: dict, *, category: str = "lead", flags: list[str] | None = None, suggested: str | None = None) -> dict:
    stored = {
        **email,
        "received_at": email.get("received_at") or "2026-10-22T12:00:00+00:00",
    }
    db.insert_email(stored)
    db.save_triage(
        email["id"],
        {
            "category": category,
            "confidence": 0.8,
            "name": email.get("from_name"),
            "company": "Gate Fixture",
            "budget": "$4,200",
            "intent": "request a proposal",
            "draft_reply": "Holding this for a person.",
            "model": "rules",
            "risk_flags": flags or [],
            "suggested_category": suggested,
            "suggestion_confidence": 0.8 if suggested else None,
            "reasons": [],
        },
    )
    row = db.get_triage_by_email(email["id"])
    assert row is not None
    full = db.get_triage(row["id"])
    assert full is not None
    return full


def _accept(client, triage_id: int, category: str = "lead", confirm: bool = False):
    return client.post(
        f"/api/triage/{triage_id}/accept",
        json={"category": category, "confirm": confirm},
    )


def test_store_cards_and_claim_codes_are_money_movement():
    assert payment_related("Could you pick up two store cards for the offsite?") is True
    assert payment_related("The refund is waiting on a claim code.") is True
    assert payment_related("Send the claim-code when you have it.") is True
    assert payment_related("Please buy an app store gift card for the raffle.") is True
    assert payment_related("Our app store listing goes live on Monday.") is False
    assert payment_related("Please use the new account for invoices.") is True
    assert payment_related("Please send future invoices to accounts@fieldnote.test instead.") is True
    assert payment_related("please also cc our AP") is False


def test_accept_cannot_promote_suspicious_even_when_flags_are_empty(client):
    row = _park(
        {
            "id": "gate-suspicious",
            "from_name": "Nora Pell",
            "from_email": "nora@pellstudio.test",
            "subject": "website refresh",
            "body": (
                "Hi Asad,\n\nCould we talk about a website refresh next month?\n\n"
                "Nora Pell\nPell Studio\n"
            ),
        },
        category="suspicious",
        flags=[],
    )
    for confirm in (False, True):
        refused = _accept(client, row["id"], confirm=confirm)
        assert refused.status_code == 409
        detail = refused.json()["detail"]
        assert detail["code"] == "suspicious"
        assert detail["message"] == "blocked: a suspicious message cannot be filed as a lead"
    side = client.post(
        "/api/crm/leads",
        json={
            "email_id": "gate-suspicious",
            "name": "Nora Pell",
            "from_email": "nora@pellstudio.test",
            "category": "lead",
            "intent": "request a proposal",
        },
    )
    assert side.status_code == 409
    assert side.json()["detail"]["code"] == "suspicious"
    assert "gate-suspicious" not in _crm_ids(client)
    assert all(item["email_id"] != "gate-suspicious" for item in db.list_filing_log())
    support = _accept(client, row["id"], category="support")
    assert support.status_code == 200
    assert support.json()["category"] == "support"
    assert "gate-suspicious" not in _crm_ids(client)


def test_brand_mismatch_is_a_security_block_not_a_confirm(client):
    row = _park(
        {
            "id": "gate-brand",
            "from_name": "PayPal",
            "from_email": "billing@paypal-notices.test",
            "subject": "receipt",
            "body": "Hi,\n\nYour receipt is ready to view.\n\nPayPal\n",
        },
        category="lead",
        flags=[],
    )
    refused = _accept(client, row["id"], confirm=True)
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["code"] == "security"
    assert detail["message"] == "blocked: verify by phone or security review"
    assert "brand_impersonation" in detail["reasons"]
    assert "gate-brand" not in _crm_ids(client)
    assert all(item["email_id"] != "gate-brand" for item in db.list_filing_log())


def test_first_contact_calendar_needs_a_logged_second_confirm(client):
    row = _park(
        {
            "id": "gate-calendar",
            "from_name": "Nora Pell",
            "from_email": "nora@pellstudio.test",
            "subject": "hold for Thursday",
            "body": (
                "Hi Asad,\n\nPlease add this hold.\n\n"
                "BEGIN:VCALENDAR\nMETHOD:REQUEST\nBEGIN:VEVENT\n"
                "SUMMARY:Thursday hold\nEND:VEVENT\nEND:VCALENDAR\n\n"
                "Nora Pell\nPell Studio\n"
            ),
        }
    )
    first = _accept(client, row["id"], confirm=False)
    assert first.status_code == 409
    detail = first.json()["detail"]
    assert detail["code"] == "confirm"
    assert "calendar invite" in detail["reasons"]
    assert "gate-calendar" not in _crm_ids(client)
    side = client.post(
        "/api/crm/leads",
        json={
            "email_id": "gate-calendar",
            "name": "Nora Pell",
            "from_email": "nora@pellstudio.test",
            "category": "lead",
            "intent": "request a proposal",
        },
    )
    assert side.status_code == 409
    assert side.json()["detail"]["code"] == "confirm"
    assert "gate-calendar" not in _crm_ids(client)
    second = _accept(client, row["id"], confirm=True)
    assert second.status_code == 200
    assert "gate-calendar" in _crm_ids(client)
    logged = [item for item in db.list_filing_log() if item["email_id"] == "gate-calendar"]
    assert len(logged) == 1
    assert logged[0]["action"] == "confirmed"
    assert "calendar invite" in logged[0]["reasons"]


def test_unknown_domain_confirms_and_a_known_sender_does_not(client):
    stranger = _park(
        {
            "id": "gate-link",
            "from_name": "Sam Idris",
            "from_email": "sam@harborandco.test",
            "subject": "the brief",
            "body": (
                "Hi Asad,\n\nDetails live at https://files.northwind-archive.test/brief\n\n"
                "Sam Idris\nHarbor and Co\n"
            ),
        }
    )
    refused = _accept(client, stranger["id"])
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "confirm"
    assert "link to an unknown domain" in refused.json()["detail"]["reasons"]
    assert "gate-link" not in _crm_ids(client)

    crm.store_lead(
        {
            "email_id": "prior-sam",
            "name": "Sam Idris",
            "email": "sam@harborandco.test",
            "company": "Harbor and Co",
            "category": "lead",
            "intent": "existing customer",
            "source_subject": "earlier work",
            "status": "Reply pending",
        }
    )
    known_unauthed = _park(
        {
            "id": "gate-known-link",
            "from_name": "Sam Idris",
            "from_email": "sam@harborandco.test",
            "subject": "updated brief",
            "body": (
                "Hi Asad,\n\nThe revised brief is at https://files.northwind-archive.test/brief\n\n"
                "Sam Idris\nHarbor and Co\n"
            ),
        }
    )
    still = _accept(client, known_unauthed["id"], confirm=False)
    assert still.status_code == 409
    assert still.json()["detail"]["code"] == "confirm"
    assert "gate-known-link" not in _crm_ids(client)
    known = _park(
        {
            "id": "gate-known-dkim",
            "from_name": "Sam Idris",
            "from_email": "sam@harborandco.test",
            "subject": "updated brief again",
            "body": (
                "Hi Asad,\n\nThe revised brief is at https://files.northwind-archive.test/brief\n\n"
                "Sam Idris\nHarbor and Co\n"
            ),
            "headers": {
                "Authentication-Results": (
                    "mx.lane.test; dkim=pass header.d=harborandco.test header.i=@harborandco.test; "
                    "spf=pass smtp.mailfrom=sam@harborandco.test; dmarc=pass header.from=harborandco.test"
                )
            },
        }
    )
    accepted = _accept(client, known["id"], confirm=False)
    assert accepted.status_code == 200
    assert "gate-known-dkim" in _crm_ids(client)
    assert all(item["email_id"] != "gate-known-dkim" for item in db.list_filing_log())


def test_same_org_link_and_a_reply_subject_still_need_confirm_without_auth(client):
    same_org = _park(
        {
            "id": "gate-same-org",
            "from_name": "Ada Field",
            "from_email": "ada@fieldnote.test",
            "subject": "pricing",
            "body": (
                "Hi Asad,\n\nThe brief is on our site: https://fieldnote.test/brief\n\n"
                "Ada Field\nFieldnote\n"
            ),
        }
    )
    same = _accept(client, same_org["id"])
    assert same.status_code == 409
    assert "link on an unauthenticated domain" in same.json()["detail"]["reasons"]
    assert "gate-same-org" not in _crm_ids(client)

    thread = _park(
        {
            "id": "gate-thread",
            "from_name": "Ada Field",
            "from_email": "ada@fieldnote.test",
            "subject": "Re: the brief",
            "body": "The short version is https://bit.ly/fieldnote-brief\n\nAda Field\n",
        }
    )
    reply = _accept(client, thread["id"], confirm=False)
    assert reply.status_code == 409
    assert "shortened link" in reply.json()["detail"]["reasons"]
    assert "gate-thread" not in _crm_ids(client)


def test_short_link_voicemail_and_filename_need_confirm_bare_attached_does_not(client):
    short = _park(
        {
            "id": "gate-short",
            "from_name": "Ada Field",
            "from_email": "ada@fieldnote.test",
            "subject": "brief",
            "body": "The brief is here: https://bit.ly/fieldnote-brief\n\nAda Field\nFieldnote\n",
        }
    )
    short_refused = _accept(client, short["id"])
    assert short_refused.status_code == 409
    assert "shortened link" in short_refused.json()["detail"]["reasons"]

    voice = _park(
        {
            "id": "gate-voice",
            "from_name": "Jules Hart",
            "from_email": "jules@hartbindery.test",
            "subject": "front desk",
            "body": (
                "You have a new voicemail from the front desk. Call back when you can.\n\n"
                "Jules Hart\nHart Bindery\n"
            ),
        }
    )
    voice_refused = _accept(client, voice["id"])
    assert voice_refused.status_code == 409
    assert voice_refused.json()["detail"]["code"] == "confirm"
    assert "voicemail notice" in voice_refused.json()["detail"]["reasons"]
    assert _accept(client, voice["id"], confirm=True).status_code == 200
    logged = [item for item in db.list_filing_log() if item["email_id"] == "gate-voice"]
    assert logged and "voicemail notice" in logged[0]["reasons"]

    named = _park(
        {
            "id": "gate-file",
            "from_name": "Rita Quill",
            "from_email": "rita@quillstudio.test",
            "subject": "scope",
            "body": "The scope is in scope-v3.pdf\n\nRita Quill\nQuill Studio\n",
        }
    )
    named_refused = _accept(client, named["id"])
    assert named_refused.status_code == 409
    assert "attachment" in named_refused.json()["detail"]["reasons"]

    bare = _park(
        {
            "id": "gate-bare-attached",
            "from_name": "Imani Brooks",
            "from_email": "imani@brooksceramics.test",
            "subject": "brochure",
            "body": (
                "Hi Asad,\n\nThe PDF is attached. Budget is $2,000 for the brochure.\n\n"
                "Thanks,\nImani Brooks\nBrooks Ceramics\n"
            ),
        }
    )
    assert _accept(client, bare["id"], confirm=False).status_code == 200
    assert "gate-bare-attached" in _crm_ids(client)


def test_a_clean_lead_still_files_on_one_click(client):
    row = _park(
        {
            "id": "gate-clean",
            "from_name": "Imani Brooks",
            "from_email": "imani@brooksceramics.test",
            "subject": "six-week tool",
            "body": (
                "Hi Asad,\n\nWe need a Python contractor for a six-week internal tool. "
                "Budget is $4,200.\n\nThanks,\nImani Brooks\nBrooks Ceramics\n"
            ),
        }
    )
    accepted = _accept(client, row["id"], confirm=False)
    assert accepted.status_code == 200
    assert "gate-clean" in _crm_ids(client)
    assert all(item["email_id"] != "gate-clean" for item in db.list_filing_log())


def test_store_card_and_claim_code_block_accept_and_a_fooled_claude(client):
    from app.pipeline import apply_policy

    store = _park(
        {
            "id": "gate-store",
            "from_name": "Lina Cho",
            "from_email": "lina@fieldnotegoods.test",
            "subject": "offsite",
            "body": (
                "Could you pick up two store cards for the offsite and leave them at the studio?\n\n"
                "Lina Cho\nFieldnote Goods\n"
            ),
        },
        category="lead",
        flags=[],
    )
    refused = _accept(client, store["id"], confirm=True)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "payment"
    assert refused.json()["detail"]["message"] == "payment-related: verify by phone"
    assert "gate-store" not in _crm_ids(client)

    claim = {
        "id": "gate-claim",
        "from_name": "Lina Cho",
        "from_email": "lina@fieldnotegoods.test",
        "subject": "refund desk",
        "body": "The refund is waiting on a claim code. Send the claim-code when you have it.\n\nLina Cho\n",
        "received_at": "2026-10-22T12:00:00+00:00",
    }
    db.insert_email(claim)
    fooled = Classification(
        category="lead",
        confidence=0.93,
        name="Lina Cho",
        company="Fieldnote Goods",
        budget="$80",
        intent="request a proposal",
        draft_reply="I can help with that.",
        model="anthropic",
        risk_flags=[],
    )
    outcome = apply_policy(claim, fooled)
    assert outcome["lead"] is None
    assert outcome["triage"]["category"] == "review"
    assert "payment_related" in outcome["triage"]["risk_flags"]
    claim_row = db.get_triage_by_email("gate-claim")
    assert claim_row is not None
    claim_refused = _accept(client, claim_row["id"], confirm=True)
    assert claim_refused.status_code == 409
    assert claim_refused.json()["detail"]["message"] == "payment-related: verify by phone"
    assert "gate-claim" not in _crm_ids(client)

    image = {
        "id": "gate-qr",
        "from_name": "Jules Hart",
        "from_email": "jules@hartbindery.test",
        "subject": "the counter",
        "body": "<p>The counter left this.</p><img src=\"cid:counter-qr\"/>",
        "received_at": "2026-10-22T12:00:00+00:00",
    }
    db.insert_email(image)
    insisted = Classification(
        category="lead",
        confidence=0.9,
        name="Jules Hart",
        company="Hart Bindery",
        budget=None,
        intent="request a proposal",
        draft_reply="Thanks for sending this.",
        model="anthropic",
        risk_flags=[],
    )
    image_outcome = apply_policy(image, insisted)
    assert image_outcome["lead"] is None
    assert "QR code" in image_outcome["triage"]["reasons"]
    image_row = db.get_triage_by_email("gate-qr")
    assert image_row is not None
    image_refused = _accept(client, image_row["id"])
    assert image_refused.status_code == 409
    assert image_refused.json()["detail"]["code"] == "confirm"
    assert "gate-qr" not in _crm_ids(client)


def test_record_command_refuses_without_a_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    dest = tmp_path / "recorded_pass.json"
    from evals.live_claude import main

    assert main(["--record", str(dest)]) == 2
    assert not dest.exists()


def test_recording_placeholder_when_no_file_exists(client, tmp_path, monkeypatch):
    monkeypatch.setenv("LANE_RECORDED_PASS", str(tmp_path / "missing.json"))
    status = client.get("/api/demo/recording")
    assert status.status_code == 200
    body = status.json()
    assert body["present"] is False
    assert body["label"] == "Recorded Claude pass: no recording yet"
    assert "no recording yet" in body["label"]
    replayed = client.post("/api/demo/replay")
    assert replayed.status_code == 404
    assert replayed.json()["detail"] == "Recorded Claude pass: no recording yet"


def test_replay_applies_a_loader_fixture_not_a_model_pass(client, tmp_path, monkeypatch):
    # Loader fixture only. This is not a Claude response and is not shipped as one.
    path = tmp_path / "loader_fixture.json"
    path.write_text(
        json.dumps(
            {
                "kind": "recorded-claude-pass",
                "recorded_at": "2026-10-22T15:04:00+00:00",
                "model": "claude-sonnet-5-5",
                "mailbox": "sample mailbox",
                "rows": [
                    {
                        "id": "m17",
                        "category": "support",
                        "confidence": 0.91,
                        "name": "Recorded Name",
                        "company": "Recorded Co",
                        "budget": None,
                        "intent": "answer a question",
                        "draft_reply": "Recorded draft from the loader fixture.",
                        "reasons": ["loader fixture"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LANE_RECORDED_PASS", str(path))
    status = client.get("/api/demo/recording")
    assert status.status_code == 200
    assert status.json()["label"] == "Recorded Claude pass, 2026-10-22, claude-sonnet-5-5, sample mailbox"
    replayed = client.post("/api/demo/replay")
    assert replayed.status_code == 200
    assert replayed.json()["applied"] == 1
    item = next(row for row in client.get("/api/triage").json()["items"] if row["email_id"] == "m17")
    assert item["draft_reply"] == "Recorded draft from the loader fixture."
    assert item["model"] == "claude-sonnet-5-5"
    assert item["name"] == "Recorded Name"


def test_recording_routes_hide_outside_demo_mode(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    assert client.get("/api/demo/recording").status_code == 404
    assert client.post("/api/demo/replay").status_code == 404
