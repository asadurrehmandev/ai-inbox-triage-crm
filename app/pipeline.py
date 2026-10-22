"""Classify, draft, file a lead, and alert. The worker and the webhook share this."""

from __future__ import annotations

from app import alerts, crm, db
from app.classifier import Classification
from app.llm import classify_email


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
            "email": email.get("from_email"),
            "budget": result.budget,
            "intent": result.intent,
            "category": result.category,
            "source_subject": email.get("subject"),
            "status": "Reply pending",
        }
    )


def notify(email: dict, result: Classification) -> dict:
    return alerts.post_alert(result.category, record_from_email(email, result))


def apply_policy(email: dict, result: Classification) -> dict:
    """Leads go to the CRM. Spam stays quiet. Everything else is saved and alerted."""
    triage = save_classification(email, result)
    lead = None
    alert = None
    if result.category == "lead":
        lead = push_lead(email, result)
        alert = notify(email, result)
    elif result.category != "spam":
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
    result = classify_email(email)
    return apply_policy(email, result)


def process_pending() -> list[dict]:
    processed = []
    for email in db.list_emails(status="new"):
        processed.append(process_email(email))
    return processed
