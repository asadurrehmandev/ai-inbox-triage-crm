"""Classify, draft, file a lead, and alert. The worker and the webhook share this."""

from __future__ import annotations

from app import alerts, crm, db
from app.classifier import Classification
from app.llm import classify_email
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
    if result.category == "suspicious":
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


def apply_policy(email: dict, result: Classification) -> dict:
    """Confident leads go to the CRM. Risky or uncertain mail is never filed."""
    triage = save_classification(email, result)
    categories = {result.category, *result.secondary_categories}
    lead = None
    alert = None
    blocked = result.category in {"spam", "suspicious", "review"} or bool(hard_flags(result.risk_flags))
    if "budget_not_in_body" in result.risk_flags:
        blocked = True
    if "lead" in categories and not blocked:
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
