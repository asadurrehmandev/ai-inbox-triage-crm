"""Sender authentication, thread identity, and invoice-address fixtures.

These messages are original. Headers are part of the fixture. They are not a
sealed QA mailbox.
"""

from email.message import EmailMessage

from app import crm, db
from app.classifier import Classification
from app.dkim_verify import verified_dkim_domains
from app.gate import authentication, sender_authenticated
from app.mailbox import parse_message
from app.pipeline import apply_policy
from app.risk import payment_related
from tests.conftest import signed_body
from tests.test_filing_gate import _accept, _crm_ids, _park


def _dkim(domain: str, *, result: str = "pass", signing: str | None = None) -> dict:
    signed = signing or domain
    return {
        "Authentication-Results": (
            f"mx.lane.test; dkim={result} header.d={signed} header.i=@{signed}; "
            f"spf=pass smtp.mailfrom=ada@{domain}; dmarc=pass header.from={domain}"
        ),
        "Received-SPF": (
            f"pass (lane.test: domain of ada@{domain} designates 203.0.113.8 as permitted sender)"
        ),
    }


def test_invoice_destinations_are_phone_blocked_and_an_added_cc_is_not():
    assert payment_related("Please send future invoices to accounts@fieldnote.test instead.") is True
    assert payment_related("Our new billing email is ledger@fieldnote.test.") is True
    assert payment_related("Please update the AP contact to ledger@fieldnote.test.") is True
    assert payment_related("Please use remit@vendor.test for invoice delivery.") is True
    assert payment_related("Please remit the monthly statements to ledger@fieldnote.test.") is True
    assert payment_related("Redirect accounts-payable correspondence to nova@vendor.test.") is True
    assert payment_related("Mail every supplier bill to payables@vendor.test.") is True
    assert payment_related("Please send payouts to the new address on file.") is True
    assert payment_related("please also cc our AP") is False
    assert payment_related("Please also CC ap@harbor.test on the next invoice.") is False
    assert (
        payment_related(
            "Please also cc our AP so they see the invoices. Our new account manager is Priya."
        )
        is False
    )
    assert (
        payment_related(
            "Please also cc our accounts payable. Priya is the new account manager for invoices."
        )
        is False
    )
    assert payment_related("Our payout preference is the Friday batch.") is False
    assert (
        payment_related(
            "We need a tool that reads remittance emails and matches the IBAN and SWIFT "
            "references to open invoices in Xero. Budget is €12,000."
        )
        is False
    )
    assert payment_related("Please send the invoices to the client when the import is done.") is False


def test_unauthenticated_same_domain_link_needs_confirm_and_aligned_dkim_does_not(client, monkeypatch):
    monkeypatch.setenv("TRUSTED_AUTHSERV_ID", "mx.lane.test")
    plain = _park(
        {
            "id": "auth-same-plain",
            "from_name": "Ada Field",
            "from_email": "ada@fieldnote.test",
            "subject": "the brief",
            "body": "The brief is on our site: https://fieldnote.test/brief\n\nAda Field\n",
        }
    )
    refused = _accept(client, plain["id"])
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "confirm"
    assert "link on an unauthenticated domain" in refused.json()["detail"]["reasons"]
    assert "auth-same-plain" not in _crm_ids(client)

    misaligned = _park(
        {
            "id": "auth-misaligned",
            "from_name": "Ada Field",
            "from_email": "ada@fieldnote.test",
            "subject": "the brief",
            "body": "The brief is on our site: https://fieldnote.test/brief\n\nAda Field\n",
            "headers": _dkim("fieldnote.test", signing="other.test"),
        }
    )
    report = authentication(
        {
            "from_email": "ada@fieldnote.test",
            "headers": _dkim("fieldnote.test", signing="other.test"),
        }
    )
    assert report["dkim"] == "pass"
    assert report["spf"] == "pass"
    assert report["dmarc"] == "pass"
    assert report["aligned"] is False
    assert _accept(client, misaligned["id"]).status_code == 409

    spf_only = _park(
        {
            "id": "auth-spf-only",
            "from_name": "Ada Field",
            "from_email": "ada@fieldnote.test",
            "subject": "the brief",
            "body": "The brief is on our site: https://fieldnote.test/brief\n\nAda Field\n",
            "headers": {
                "Authentication-Results": (
                    "mx.lane.test; spf=pass smtp.mailfrom=ada@fieldnote.test; "
                    "dmarc=pass header.from=fieldnote.test"
                ),
                "Received-SPF": "pass (lane.test: domain of ada@fieldnote.test designates 203.0.113.8)",
            },
        }
    )
    spf_report = authentication(
        {
            "from_email": "ada@fieldnote.test",
            "headers": {
                "Authentication-Results": (
                    "mx.lane.test; spf=pass smtp.mailfrom=ada@fieldnote.test; "
                    "dmarc=pass header.from=fieldnote.test"
                )
            },
        }
    )
    assert spf_report["spf"] == "pass"
    assert spf_report["dmarc"] == "pass"
    assert spf_report["dkim"] == "none"
    assert spf_report["aligned"] is False
    assert _accept(client, spf_only["id"]).status_code == 409

    passed = _park(
        {
            "id": "auth-same-dkim",
            "from_name": "Ada Field",
            "from_email": "ada@fieldnote.test",
            "subject": "the brief",
            "body": "The brief is on our site: https://fieldnote.test/brief\n\nAda Field\n",
            "headers": _dkim("fieldnote.test"),
        }
    )
    # Authenticated, but not a known sender and not a stored thread: the same-domain
    # link itself is no longer a feature, so a link-only note can be filed.
    assert _accept(client, passed["id"]).status_code == 200
    assert "auth-same-dkim" in _crm_ids(client)


def test_qr_meeting_voicemail_quota_and_login_always_confirm(client, monkeypatch):
    monkeypatch.setenv("TRUSTED_AUTHSERV_ID", "mx.lane.test")
    crm.store_lead(
        {
            "email_id": "prior-ada",
            "name": "Ada Field",
            "email": "ada@fieldnote.test",
            "company": "Fieldnote",
            "category": "lead",
            "intent": "existing customer",
            "source_subject": "earlier",
            "status": "Reply pending",
        }
    )
    headers = _dkim("fieldnote.test")
    cases = [
        (
            "auth-qr",
            '<img src="https://fieldnote.test/qr.png" alt="desk code"/>\n\nAda Field\n',
            "QR code",
        ),
        (
            "auth-meeting",
            "Your meeting is starting. Join at https://fieldnote.test/room\n\nAda Field\n",
            "meeting starting",
        ),
        (
            "auth-voice",
            "You have a new voicemail from the front desk.\n\nAda Field\n",
            "voicemail notice",
        ),
        (
            "auth-quota",
            "Your mailbox quota has been exceeded.\n<form action=\"https://fieldnote.test/quota\">"
            "<button>Open</button></form>\n\nAda Field\n",
            "quota or storage notice",
        ),
        (
            "auth-login",
            "Continue at https://fieldnote.test/login/reset\n\nAda Field\n",
            "login or form link",
        ),
    ]
    for email_id, body, reason in cases:
        row = _park(
            {
                "id": email_id,
                "from_name": "Ada Field",
                "from_email": "ada@fieldnote.test",
                "subject": "a note",
                "body": body,
                "headers": headers,
            }
        )
        refused = _accept(client, row["id"], confirm=False)
        assert refused.status_code == 409, email_id
        assert refused.json()["detail"]["code"] == "confirm"
        assert reason in refused.json()["detail"]["reasons"], email_id
        assert email_id not in _crm_ids(client)
        filed = _accept(client, row["id"], confirm=True)
        assert filed.status_code == 200, email_id
        assert email_id in _crm_ids(client)


def test_a_cid_logo_does_not_require_confirm_and_an_off_domain_image_does(client):
    logo = _park(
        {
            "id": "auth-cid-logo",
            "from_name": "Ada Field",
            "from_email": "ada@fieldnote.test",
            "subject": "hello",
            "body": '<p>Our logo.</p><img src="cid:logo"/>\n\nAda Field\n',
        }
    )
    assert _accept(client, logo["id"]).status_code == 200
    assert "auth-cid-logo" in _crm_ids(client)

    remote = _park(
        {
            "id": "auth-remote-img",
            "from_name": "Ada Field",
            "from_email": "ada@fieldnote.test",
            "subject": "hello",
            "body": '<p>Logo</p><img src="https://cdn.other.test/logo.png"/>\n\nAda Field\n',
        }
    )
    refused = _accept(client, remote["id"])
    assert refused.status_code == 409
    assert "image on an unknown domain" in refused.json()["detail"]["reasons"]


def test_reply_thread_requires_a_stored_message_id_and_aligned_dkim(client, monkeypatch):
    monkeypatch.setenv("TRUSTED_AUTHSERV_ID", "mx.lane.test")
    db.insert_email(
        {
            "id": "thread-parent",
            "message_id": "prior-mara-1@quillstudio.test",
            "from_name": "Mara Quill",
            "from_email": "mara@quillstudio.test",
            "subject": "the brochure",
            "body": "Hi Asad,\n\nBudget is $2,000 for the brochure.\n\nMara Quill\n",
            "received_at": "2026-10-21T12:00:00+00:00",
        }
    )
    hijack = _park(
        {
            "id": "thread-hijack",
            "from_name": "Mara Quill",
            "from_email": "mara@other.test",
            "subject": "Re: the brochure",
            "body": "The new page is https://other.test/portal\n\nMara\n",
            "in_reply_to": "<prior-mara-1@quillstudio.test>",
            "references": "<prior-mara-1@quillstudio.test>",
            "headers": {
                "In-Reply-To": "<prior-mara-1@quillstudio.test>",
                "References": "<prior-mara-1@quillstudio.test>",
            },
        }
    )
    hijack_refused = _accept(client, hijack["id"])
    assert hijack_refused.status_code == 409
    assert "link on an unauthenticated domain" in hijack_refused.json()["detail"]["reasons"]
    assert "thread-hijack" not in _crm_ids(client)

    clean = _park(
        {
            "id": "thread-clean",
            "from_name": "Mara Quill",
            "from_email": "mara@quillstudio.test",
            "subject": "Re: the brochure",
            "body": "Hi Asad,\n\nStill $2,000 for the brochure.\n\nMara Quill\n",
            "in_reply_to": "<prior-mara-1@quillstudio.test>",
            "references": "<prior-mara-1@quillstudio.test>",
            "headers": {
                **_dkim("quillstudio.test"),
                "In-Reply-To": "<prior-mara-1@quillstudio.test>",
                "References": "<prior-mara-1@quillstudio.test>",
            },
        }
    )
    assert _accept(client, clean["id"], confirm=False).status_code == 200
    assert "thread-clean" in _crm_ids(client)

    checkout = _park(
        {
            "id": "thread-checkout",
            "from_name": "Mara Quill",
            "from_email": "mara@quillstudio.test",
            "subject": "Re: the brochure",
            "body": (
                "Hi Asad,\n\nThe checkout link for the deposit is "
                "https://quillstudio.test/checkout/88\n\nMara Quill\n"
            ),
            "in_reply_to": "<prior-mara-1@quillstudio.test>",
            "headers": {
                **_dkim("quillstudio.test"),
                "In-Reply-To": "<prior-mara-1@quillstudio.test>",
            },
        }
    )
    checkout_refused = _accept(client, checkout["id"])
    assert checkout_refused.status_code == 409
    assert "checkout link" in checkout_refused.json()["detail"]["reasons"]
    assert "thread-checkout" not in _crm_ids(client)

    addendum = _park(
        {
            "id": "thread-addendum",
            "from_name": "Mara Quill",
            "from_email": "mara@quillstudio.test",
            "subject": "Re: the brochure",
            "body": "Hi Asad,\n\nAttached in spirit: a payment addendum for the deposit.\n\nMara Quill\n",
            "in_reply_to": "<prior-mara-1@quillstudio.test>",
            "headers": {
                **_dkim("quillstudio.test"),
                "In-Reply-To": "<prior-mara-1@quillstudio.test>",
            },
        }
    )
    addendum_refused = _accept(client, addendum["id"])
    assert addendum_refused.status_code == 409
    assert addendum_refused.json()["detail"]["code"] == "confirm"
    assert "payment addendum" in addendum_refused.json()["detail"]["reasons"]

    terms = _park(
        {
            "id": "thread-terms",
            "from_name": "Mara Quill",
            "from_email": "mara@quillstudio.test",
            "subject": "Re: the brochure",
            "body": "Hi Asad,\n\nThe updated terms are in the note I just sent.\n\nMara Quill\n",
            "in_reply_to": "<prior-mara-1@quillstudio.test>",
            "headers": {
                **_dkim("quillstudio.test"),
                "In-Reply-To": "<prior-mara-1@quillstudio.test>",
            },
        }
    )
    terms_refused = _accept(client, terms["id"])
    assert terms_refused.status_code == 409
    assert "changed terms" in terms_refused.json()["detail"]["reasons"]


def test_invoice_redirect_stays_blocked_and_an_ap_cc_can_be_confirmed(client):
    redirect = _park(
        {
            "id": "auth-redirect",
            "from_name": "Lina Cho",
            "from_email": "lina@fieldnotegoods.test",
            "subject": "billing",
            "body": (
                "Hi Asad,\n\nPlease send future invoices to accounts@fieldnote.test instead.\n\n"
                "Lina Cho\n"
            ),
            "headers": _dkim("fieldnotegoods.test"),
        }
    )
    refused = _accept(client, redirect["id"], confirm=True)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "payment"
    assert refused.json()["detail"]["message"] == "payment-related: verify by phone"
    assert "auth-redirect" not in _crm_ids(client)

    copied = _park(
        {
            "id": "auth-cc-ap",
            "from_name": "Lina Cho",
            "from_email": "lina@fieldnotegoods.test",
            "subject": "brochure",
            "body": (
                "Hi Asad,\n\nWe'd like the brochure. Budget is $2,000. "
                "Please also cc our AP.\n\nLina Cho\n"
            ),
        }
    )
    first = _accept(client, copied["id"])
    assert first.status_code == 409
    assert first.json()["detail"]["code"] == "confirm"
    assert "also copy accounts payable" in first.json()["detail"]["reasons"]
    assert "auth-cc-ap" not in _crm_ids(client)
    second = _accept(client, copied["id"], confirm=True)
    assert second.status_code == 200
    assert "auth-cc-ap" in _crm_ids(client)
    logged = [item for item in db.list_filing_log() if item["email_id"] == "auth-cc-ap"]
    assert logged and "also copy accounts payable" in logged[0]["reasons"]


def test_claude_autofile_is_lead_only_and_skips_receipts(client):
    receipt = {
        "id": "auth-receipt",
        "from_name": "Mara Quill",
        "from_email": "mara@quillstudio.test",
        "subject": "workshop",
        "body": "Receipt for the workshop. Paid in full.\n\nMara Quill\n",
        "received_at": "2026-10-22T12:00:00+00:00",
    }
    db.insert_email(receipt)
    fooled = Classification(
        category="lead",
        confidence=0.92,
        name="Mara Quill",
        company="Quill Studio",
        budget="$80",
        intent="request a proposal",
        draft_reply="Thanks for this.",
        model="anthropic",
        risk_flags=[],
    )
    outcome = apply_policy(receipt, fooled)
    assert outcome["lead"] is None
    assert "receipts and invoices are not auto-filed" in outcome["triage"]["reasons"]
    row = db.get_triage_by_email("auth-receipt")
    assert row is not None
    assert _accept(client, row["id"]).status_code == 200
    assert "auth-receipt" in _crm_ids(client)

    invoice = {
        "id": "auth-invoice-doc",
        "from_name": "Mara Quill",
        "from_email": "mara@quillstudio.test",
        "subject": "hosting",
        "body": "Hi Asad,\n\nInvoice 4412 for hosting is ready.\n\nMara Quill\n",
        "received_at": "2026-10-22T12:00:00+00:00",
    }
    db.insert_email(invoice)
    labeled = Classification(
        category="invoice",
        confidence=0.9,
        name="Mara Quill",
        company="Quill Studio",
        budget="$40",
        intent="record an invoice",
        draft_reply="Received.",
        model="anthropic",
    )
    assert apply_policy(invoice, labeled)["lead"] is None
    assert "auth-invoice-doc" not in _crm_ids(client)


def test_imap_keeps_authentication_and_thread_headers(monkeypatch):
    monkeypatch.setenv("TRUSTED_AUTHSERV_ID", "mx.lane.test")
    message = EmailMessage()
    message["From"] = "Ada Field <ada@fieldnote.test>"
    message["Subject"] = "the brief"
    message["Date"] = "Thu, 22 Oct 2026 12:00:00 +0000"
    message["Message-ID"] = "<brief-9@fieldnote.test>"
    message["In-Reply-To"] = "<prior-1@fieldnote.test>"
    message["References"] = "<prior-1@fieldnote.test>"
    message["Authentication-Results"] = (
        "mx.lane.test; dkim=pass header.d=fieldnote.test; spf=pass; dmarc=pass"
    )
    parsed = parse_message(message.as_bytes(), "1", "42")
    assert parsed["message_id"] == "brief-9@fieldnote.test"
    assert parsed["in_reply_to"] == "<prior-1@fieldnote.test>"
    assert "prior-1@fieldnote.test" in parsed["references"]
    report = authentication({"from_email": parsed["from_email"], "headers": parsed["headers"]})
    assert report["dkim"] == "pass"
    assert report["aligned"] is True
    # The raw message has no DKIM signature. Once that check is stored, the
    # Authentication-Results header on the same message is not proof.
    assert parsed.get("dkim_verified") == "none"
    checked = authentication(parsed)
    assert checked["aligned"] is False


def _quote(headers: dict) -> dict:
    return {
        "id": "auth-forged",
        "from_name": "Pat Shore",
        "from_email": "pat@harborline.test",
        "subject": "a quote",
        "body": "The quote is on our site: https://harborline.test/quote\n\nPat Shore\n",
        "headers": headers,
    }


def test_forged_duplicate_and_lookalike_authserv_ids_are_not_trusted(client, monkeypatch):
    monkeypatch.delenv("TRUSTED_AUTHSERV_ID", raising=False)
    honest = {
        "from_email": "pat@harborline.test",
        "headers": _dkim("harborline.test"),
    }
    unset = authentication(honest)
    assert unset["dkim"] == "none"
    assert unset["aligned"] is False
    assert sender_authenticated(honest) is False

    monkeypatch.setenv("TRUSTED_AUTHSERV_ID", "mx.lane.test")
    forged_headers = {
        "Authentication-Results": (
            "evil.attacker; dkim=pass header.d=harborline.test header.i=@harborline.test"
        )
    }
    forged = _park(_quote(forged_headers))
    forged_report = authentication({"from_email": "pat@harborline.test", "headers": forged_headers})
    assert forged_report["dkim"] == "none"
    assert forged_report["aligned"] is False
    refused = _accept(client, forged["id"])
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "confirm"
    assert "link on an unauthenticated domain" in refused.json()["detail"]["reasons"]
    assert "auth-forged" not in _crm_ids(client)

    lookalikes = [
        "mx.lane.test.attacker.com; dkim=pass header.d=harborline.test",
        "notmx.lane.test; dkim=pass header.d=harborline.test",
        "MX.LANE.TEST.evil; dkim=pass header.d=harborline.test",
    ]
    for index, blob in enumerate(lookalikes):
        row = _park({**_quote({"Authentication-Results": blob}), "id": f"auth-lookalike-{index}"})
        report = authentication({"from_email": "pat@harborline.test", "headers": {"Authentication-Results": blob}})
        assert report["aligned"] is False
        assert _accept(client, row["id"]).status_code == 409
        assert f"auth-lookalike-{index}" not in _crm_ids(client)

    # The forged pass is above the trusted result, so it is ignored. The trusted one passes.
    stacked = authentication(
        {
            "from_email": "pat@harborline.test",
            "headers": {
                "Authentication-Results": [
                    "evil.attacker; dkim=pass header.d=harborline.test",
                    "mx.lane.test; dkim=pass header.d=harborline.test",
                ]
            },
        }
    )
    assert stacked["aligned"] is True
    assert stacked["dkim"] == "pass"

    # A later copy of the trusted id cannot overrule the topmost trusted result.
    duplicate = authentication(
        {
            "from_email": "pat@harborline.test",
            "headers": {
                "Authentication-Results": [
                    "mx.lane.test; dkim=fail header.d=harborline.test",
                    "mx.lane.test; dkim=pass header.d=harborline.test",
                ],
                "ARC-Authentication-Results": "i=1; mx.lane.test; dkim=pass header.d=harborline.test",
            },
        }
    )
    assert duplicate["dkim"] == "none"
    assert duplicate["aligned"] is False

    arc_only = authentication(
        {
            "from_email": "pat@harborline.test",
            "headers": {
                "ARC-Authentication-Results": "i=1; evil.attacker; dkim=pass header.d=harborline.test",
            },
        }
    )
    assert arc_only["aligned"] is False
    trusted_arc = authentication(
        {
            "from_email": "pat@harborline.test",
            "headers": {
                "ARC-Authentication-Results": "i=1; mx.lane.test; dkim=pass header.d=harborline.test",
            },
        }
    )
    assert trusted_arc["aligned"] is True

    real = _park({**_quote(_dkim("harborline.test")), "id": "auth-trusted-provider"})
    assert _accept(client, real["id"]).status_code == 200
    assert "auth-trusted-provider" in _crm_ids(client)


def test_webhook_forged_auth_header_does_not_authenticate(client, monkeypatch):
    monkeypatch.setenv("TRUSTED_AUTHSERV_ID", "mx.lane.test")
    payload = {
        "from_name": "Pat Shore",
        "from_email": "pat@harborline.test",
        "subject": "a quote",
        "body": "The quote is on our site: https://harborline.test/quote\n\nPat Shore\n",
        "headers": {
            "Authentication-Results": "evil.attacker; dkim=pass header.d=harborline.test",
            "dkim_verified": "harborline.test",
        },
    }
    raw, signed = signed_body(payload)
    ingested = client.post("/api/webhooks/email", content=raw, headers=signed)
    assert ingested.status_code == 200
    stored = db.get_email(ingested.json()["id"])
    assert stored is not None
    assert stored.get("dkim_verified") in ("", None)
    report = authentication(stored)
    assert report["aligned"] is False
    assert report["dkim"] == "none"


def test_checked_signature_overrides_a_forged_auth_header(monkeypatch):
    monkeypatch.delenv("TRUSTED_AUTHSERV_ID", raising=False)
    message = EmailMessage()
    message["From"] = "Ada Field <ada@fieldnote.test>"
    message["Subject"] = "the brief"
    message["Authentication-Results"] = "evil.attacker; dkim=pass header.d=fieldnote.test"
    message.set_content("The brief is ready.\n")
    raw = message.as_bytes()
    unsigned = verified_dkim_domains(raw)
    assert unsigned == []
    forged = {
        "from_email": "ada@fieldnote.test",
        "headers": {"Authentication-Results": "evil.attacker; dkim=pass header.d=fieldnote.test"},
        "raw_message": raw,
    }
    assert sender_authenticated(forged) is False

    monkeypatch.setattr(
        "app.gate.verified_dkim_domains",
        lambda _raw: ["fieldnote.test"],
    )
    assert sender_authenticated(forged) is True
    monkeypatch.setattr("app.gate.verified_dkim_domains", lambda _raw: [])
    monkeypatch.setenv("TRUSTED_AUTHSERV_ID", "mx.lane.test")
    trusted_header = {
        "from_email": "ada@fieldnote.test",
        "headers": _dkim("fieldnote.test"),
        "raw_message": raw,
    }
    # Bytes were checked and the signature did not pass, so the header cannot.
    assert sender_authenticated(trusted_header) is False


def test_voice_message_needs_the_same_confirm_as_voicemail(client, monkeypatch):
    monkeypatch.setenv("TRUSTED_AUTHSERV_ID", "mx.lane.test")
    crm.store_lead(
        {
            "email_id": "prior-ada-voice",
            "name": "Ada Field",
            "email": "ada@fieldnote.test",
            "company": "Fieldnote",
            "category": "lead",
            "intent": "existing customer",
            "source_subject": "earlier",
            "status": "Reply pending",
        }
    )
    row = _park(
        {
            "id": "auth-voice-message",
            "from_name": "Ada Field",
            "from_email": "ada@fieldnote.test",
            "subject": "a note",
            "body": "You have a new voice message waiting at the front desk.\n\nAda Field\n",
            "headers": _dkim("fieldnote.test"),
        }
    )
    refused = _accept(client, row["id"])
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "confirm"
    assert "voicemail notice" in refused.json()["detail"]["reasons"]
    assert "auth-voice-message" not in _crm_ids(client)
    filed = _accept(client, row["id"], confirm=True)
    assert filed.status_code == 200
    assert "auth-voice-message" in _crm_ids(client)


def test_added_ap_copy_stays_confirm_when_the_note_mentions_invoices(client):
    copied = _park(
        {
            "id": "auth-cc-invoices",
            "from_name": "Lina Cho",
            "from_email": "lina@fieldnotegoods.test",
            "subject": "brochure",
            "body": (
                "Hi Asad,\n\nWe'd like the brochure. Budget is $2,000. "
                "Please also cc our AP so they see the invoices. "
                "Our new account manager is Priya.\n\nLina Cho\n"
            ),
        }
    )
    first = _accept(client, copied["id"])
    assert first.status_code == 409
    assert first.json()["detail"]["code"] == "confirm"
    assert "also copy accounts payable" in first.json()["detail"]["reasons"]
    assert "auth-cc-invoices" not in _crm_ids(client)
    second = _accept(client, copied["id"], confirm=True)
    assert second.status_code == 200
    assert "auth-cc-invoices" in _crm_ids(client)
