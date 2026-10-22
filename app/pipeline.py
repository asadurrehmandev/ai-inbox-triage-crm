"""Classify, draft, file a lead, and alert. The worker and the webhook share this."""

from __future__ import annotations

from app import alerts, crm, db
from app.classifier import Classification
from app.llm import classify_email
from app.gate import evaluate_filing, is_receipt_or_invoice, log_confirmed_filing
from app.normalize import open_channels
from app.prepare import html_to_text, strip_quotes
from app.risk import hard_flags


def record_from_email(email: dict, result: Classification) -> dict:
    return {
        "email_id": email["id"],
        "from_name": email.get("from_name"),
        "from_email": email.get("from_email"),
        "subject": email.get("subject"),
        "name": result.name,
        "company": result.company,
        "budget": result.budget,
        "intent": result.intent,
        "category": result.category,
    }


def save_classification(email: dict, result: Classification) -> dict:
    return db.save_triage(email["id"], result.as_dict())


def push_lead(email: dict, result: Classification) -> dict:
    return crm.store_lead(
        {
            "email_id": email["id"],
            "name": result.name,
            "company": result.company,
            "email": result.contact_email or email.get("from_email"),
            "budget": result.budget,
            "intent": result.intent,
            "category": "lead",
            "source_subject": email.get("subject"),
            "status": "Reply pending",
        }
    )


def notify(email: dict, result: Classification) -> dict:
    if hard_flags(result.risk_flags) or result.category == "suspicious":
        return alerts.post_alert(
            "suspicious",
            record_from_email(email, result),
            title="Possible phishing — do not pay or reply",
            body=result.draft_reply,
        )
    if result.category == "review":
        return alerts.post_alert(
            "review",
            record_from_email(email, result),
            title="Needs review",
            body=result.draft_reply,
        )
    return alerts.post_alert(result.category, record_from_email(email, result))


def readable_text(email: dict) -> str:
    channels = open_channels(email.get("body") or "")
    visible = strip_quotes(channels.visible or html_to_text(email.get("body") or ""))
    return f"{email.get('subject') or ''}\n{visible}\n{channels.concealed}"


def _rules_mode(result: Classification) -> bool:
    return (result.model or "rules").startswith("rules")


def _known_contacts() -> list[dict]:
    return [
        {"name": row.get("name"), "email": row.get("email")}
        for row in db.list_leads()
        if row.get("email")
    ]


def apply_policy(email: dict, result: Classification, known_contacts: list[dict] | None = None) -> dict:
    """Rules mode never writes the CRM. Claude uses the same gate as Accept.

    The gate reads the message again. A wrong category or an empty flag list
    does not open the CRM. confirmed is never passed here: auto-file cannot
    supply the second confirm a person has to click.
    """
    contacts = _known_contacts() if known_contacts is None else known_contacts
    wants_lead = (
        result.category == "lead"
        or result.suggested_category == "lead"
        or "lead" in result.secondary_categories
    )
    if wants_lead:
        decision = evaluate_filing(
            email,
            current_category=result.category,
            target="lead",
            known_contacts=contacts,
            confirmed=False,
        )
        if decision.code == "payment":
            result.suggested_category = result.suggested_category or "lead"
            result.category = "review"
            if "payment_related" not in result.risk_flags:
                result.risk_flags = [*result.risk_flags, "payment_related"]
            result.reasons = list(dict.fromkeys([*result.reasons, *decision.reasons]))
        elif decision.code in {"security", "suspicious"}:
            result.category = "suspicious"
            extra = [reason for reason in decision.reasons if reason != "category is suspicious"]
            result.risk_flags = list(dict.fromkeys([*result.risk_flags, *extra]))
        elif decision.needs_confirm:
            result.reasons = list(dict.fromkeys([*result.reasons, *decision.reasons]))
    # A receipt or an invoice is never auto-filed, even when the model said lead.
    receipt = is_receipt_or_invoice(email)
    if receipt and result.category == "lead" and not _rules_mode(result):
        result.reasons = list(dict.fromkeys([*result.reasons, "receipts and invoices are not auto-filed"]))
    triage = save_classification(email, result)
    lead = None
    alert = None
    if not _rules_mode(result) and result.category == "lead" and not receipt:
        filed = evaluate_filing(
            email,
            current_category=result.category,
            target="lead",
            known_contacts=contacts,
            confirmed=False,
        )
        if filed.allow and not hard_flags(result.risk_flags):
            lead = push_lead(email, result)
    if result.category != "spam":
        alert = notify(email, result)
    db.set_status(email["id"], "triaged")
    return {"triage": db.public_triage({**triage, **_email_fields(email)}), "lead": lead, "alert": alert}


def _email_fields(email: dict) -> dict:
    return {
        "subject": email.get("subject"),
        "mailbox_name": email.get("from_name"),
        "from_email": email.get("from_email"),
        "body": email.get("body"),
        "received_at": email.get("received_at"),
    }


def accept_suggestion(row: dict, category: str | None = None, *, confirmed: bool = False) -> dict:
    """Apply the reviewer's label. The filing gate runs here, not in the button."""
    target = category or row.get("suggested_category")
    if target not in {"lead", "support", "invoice", "spam", "urgent", "suspicious"}:
        raise ValueError("no suggested label")
    email = {
        "id": row["email_id"],
        "from_email": row.get("from_email"),
        "from_name": row.get("mailbox_name") or row.get("from_name"),
        "subject": row.get("subject"),
        "body": row.get("body") or "",
        "message_id": row.get("message_id") or "",
        "in_reply_to": row.get("in_reply_to") or "",
        "references": row.get("references_header") or row.get("references") or "",
        "headers": row.get("headers") or "",
    }
    decision = evaluate_filing(
        email,
        current_category=row.get("category"),
        target=target,
        known_contacts=_known_contacts(),
        confirmed=confirmed,
    )
    decision.raise_if_refused()
    if decision.code == "confirmed":
        log_confirmed_filing(str(row.get("email_id") or ""), decision.reasons)
    confidence = float(row.get("suggestion_confidence") or 0.7)
    updated = db.accept_category(row["id"], target, confidence)
    if updated is None:
        raise KeyError(row["id"])
    lead = None
    if target == "lead":
        result = Classification(
            category="lead",
            confidence=confidence,
            name=row.get("name"),
            company=row.get("company"),
            budget=row.get("budget"),
            intent=row.get("intent") or "",
            draft_reply=row.get("draft_reply") or "",
            contact_email=row.get("from_email"),
        )
        lead = push_lead(email, result)
    return {"triage": db.public_triage(updated, full_body=True), "lead": lead}


def process_email(email: dict) -> dict:
    contacts = [
        {"name": row.get("name"), "email": row.get("email")}
        for row in db.list_leads()
        if row.get("name") and row.get("email")
    ]
    result = classify_email(email, contacts)
    return apply_policy(email, result)


def process_pending() -> list[dict]:
    import logging

    log = logging.getLogger("lane.pipeline")
    processed = []
    for email in db.list_emails(status="new"):
        try:
            processed.append(process_email(email))
        except Exception:
            log.exception("message_failed id=%s", email.get("id"))
    return processed
