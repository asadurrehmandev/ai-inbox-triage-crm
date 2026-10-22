"""Slack-style alerts. The local feed is the mock webhook."""

from __future__ import annotations

import os

import httpx

from app import db


def escape_mrkdwn(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_alert(category: str, record: dict) -> tuple[str, str]:
    name = escape_mrkdwn(str(record.get("name") or record.get("from_name") or "Unknown sender"))
    company = escape_mrkdwn(str(record.get("company") or "no company on file"))
    budget = escape_mrkdwn(str(record.get("budget") or "no amount stated"))
    intent = escape_mrkdwn(str(record.get("intent") or "review the message"))
    subject = escape_mrkdwn(str(record.get("subject") or record.get("source_subject") or ""))
    if category == "lead":
        title = "Qualified lead"
        body = f"{name} at {company}. {budget}. {intent}. {subject}".strip()
    elif category == "urgent":
        title = "Urgent — jump the queue"
        body = f"{name} at {company}. {intent}. {subject}".strip()
    elif category == "invoice":
        title = "Invoice to reconcile"
        body = f"{name} at {company}. {budget}. {intent}."
    elif category == "support":
        title = "Support waiting"
        body = f"{name} at {company}. {intent}. {subject}".strip()
    elif category == "suspicious":
        title = "Possible phishing — do not pay or reply"
        body = f"{name} at {company}. {subject}".strip()
    else:
        title = "Filed without a reply"
        body = f"{subject}".strip()
    return title, body


def post_alert(category: str, record: dict, title: str | None = None, body: str | None = None) -> dict:
    rendered_title, rendered_body = render_alert(category, record)
    title = title or rendered_title
    body = body or rendered_body
    stored = db.insert_alert(
        {
            "email_id": record.get("email_id"),
            "category": category,
            "title": title,
            "body": body,
        }
    )
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if webhook:
        try:
            response = httpx.post(webhook, json={"text": f"*{escape_mrkdwn(title)}*\n{body}"}, timeout=10)
            stored["delivered"] = response.is_success
            if not response.is_success:
                stored["delivery_error"] = f"HTTP {response.status_code}"
        except Exception as exc:
            stored["delivered"] = False
            stored["delivery_error"] = type(exc).__name__
    else:
        stored["delivered"] = False
        stored["delivery"] = "mock"
    return stored
