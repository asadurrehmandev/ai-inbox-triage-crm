"""Classify, draft, file a lead, and alert. The worker and the webhook share this."""

from __future__ import annotations

from app import alerts, crm, db
from app.classifier import Classification
from app.llm import classify_email
from app.prepare import html_to_text, strip_quotes
from app.risk import blocks_autofile, hard_flags, money_movement


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


def apply_policy(email: dict, result: Classification) -> dict:
    """Confident leads go to the CRM. Risky or uncertain mail is never filed."""
    visible = strip_quotes(html_to_text(email.get("body") or ""))
    if result.category == "urgent" and (hard_flags(result.risk_flags) or money_movement(visible)):
        result.category = "suspicious" if hard_flags(result.risk_flags) else "review"
    if result.category == "lead" and money_movement(visible):
        result.suggested_category = result.suggested_category or "lead"
        result.category = "review"
    triage = save_classification(email, result)
    categories = {result.category, *result.secondary_categories}
    lead = None
    alert = None
    blocked = blocks_autofile(email, visible, result.risk_flags, result.budget, result.category)
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


def accept_suggestion(row: dict, category: str | None = None) -> dict:
    """Apply the reviewer's one-click label. A payment request is still not filed."""
    target = category or row.get("suggested_category")
    if target not in {"lead", "support", "invoice", "spam", "urgent", "suspicious"}:
        raise ValueError("no suggested label")
    flags = [item for item in (row.get("risk_flags") or []) if item]
    if isinstance(row.get("risk_flags"), str):
        flags = [item for item in row["risk_flags"].split(",") if item]
    email = {
        "id": row["email_id"],
        "from_email": row.get("from_email"),
        "from_name": row.get("mailbox_name") or row.get("from_name"),
        "subject": row.get("subject"),
        "body": row.get("body") or "",
    }
    visible = strip_quotes(html_to_text(email["body"]))
    if target == "lead" and blocks_autofile(email, visible, flags, row.get("budget"), "lead"):
        raise PermissionError("payment change")
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
