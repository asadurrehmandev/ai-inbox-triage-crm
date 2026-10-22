"""HTTP API: webhook ingest, classification, and the desk the worker fills."""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import alerts, crm, db
from app.classifier import Classification
from app.llm import classify_email, select_provider
from app.mailbox import mailbox_mode
from app.pipeline import push_lead, save_classification
from app.seed import reset_demo, seed_if_empty
from app.worker import run_once, start_worker, status as worker_status, stop_worker

MINUTES_PER_EMAIL = 6
PROJECTED_DAILY_VOLUME = 80


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    seed_if_empty()
    start_worker()
    try:
        yield
    finally:
        stop_worker()


app = FastAPI(title="Lane inbox triage", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class EmailIn(BaseModel):
    email_id: str | None = None
    subject: str = ""
    body: str = ""
    from_name: str = ""
    from_email: str = ""


class TriageIn(BaseModel):
    email_id: str
    category: str
    confidence: float
    name: str | None = None
    company: str | None = None
    budget: str | None = None
    intent: str
    draft_reply: str
    model: str = "rules"


class DraftIn(BaseModel):
    draft_reply: str = Field(min_length=1)


class LeadIn(BaseModel):
    email_id: str
    name: str | None = None
    company: str | None = None
    from_email: str | None = None
    budget: str | None = None
    intent: str | None = None
    category: str = "lead"
    subject: str | None = None


class WebhookEmail(BaseModel):
    message_id: str | None = None
    from_name: str = ""
    from_email: str
    subject: str
    body: str
    received_at: str | None = None


class AlertIn(BaseModel):
    email_id: str | None = None
    category: str
    title: str | None = None
    body: str | None = None
    name: str | None = None
    company: str | None = None
    budget: str | None = None
    intent: str | None = None
    subject: str | None = None


def _email_or_404(email_id: str) -> dict:
    email = db.get_email(email_id)
    if email is None:
        raise HTTPException(status_code=404, detail=f"No message {email_id}")
    return email


def _classification(payload: TriageIn) -> Classification:
    return Classification(
        category=payload.category,
        confidence=payload.confidence,
        name=payload.name,
        company=payload.company,
        budget=payload.budget,
        intent=payload.intent,
        draft_reply=payload.draft_reply,
        model=payload.model,
    )


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "lane-triage",
        "mode": select_provider(),
        "mailbox": mailbox_mode(),
        "crm": crm.destination_label(),
        "worker": worker_status(),
    }


@app.get("/api/stats")
def stats() -> dict:
    emails = db.list_emails()
    triage = db.list_triage()
    leads = db.list_leads()
    by_category = {name: 0 for name in ("lead", "support", "invoice", "spam", "urgent")}
    approved = 0
    for item in triage:
        by_category[item["category"]] = by_category.get(item["category"], 0) + 1
        if item["approved"]:
            approved += 1
    processed = len(triage)
    return {
        "processed": processed,
        "waiting": sum(1 for email in emails if email["status"] == "new"),
        "pending_approval": processed - approved,
        "approved": approved,
        "leads": len(leads),
        "alerts": len(db.list_alerts()),
        "by_category": by_category,
        "hours_saved": round(processed * MINUTES_PER_EMAIL / 60, 1),
        "minutes_per_email": MINUTES_PER_EMAIL,
        "projected_daily_hours": round(PROJECTED_DAILY_VOLUME * MINUTES_PER_EMAIL / 60, 1),
        "projected_daily_volume": PROJECTED_DAILY_VOLUME,
        "mode": select_provider(),
        "mailbox": mailbox_mode(),
        "crm": crm.destination_label(),
    }


@app.get("/api/intake/pending")
def pending() -> dict:
    return {"emails": db.list_emails(status="new")}


@app.post("/api/webhooks/email")
def ingest_email(payload: WebhookEmail) -> dict:
    """Inbound mail from Gmail forwarding, Outlook, or any HTTP hook."""
    email_id = (payload.message_id or "").strip() or f"wh-{uuid4().hex[:10]}"
    db.insert_email(
        {
            "id": email_id,
            "from_name": payload.from_name,
            "from_email": payload.from_email,
            "subject": payload.subject,
            "body": payload.body,
            "received_at": payload.received_at or db.now(),
        }
    )
    return {"id": email_id, "status": "queued"}


@app.get("/api/worker")
def worker() -> dict:
    return worker_status()


@app.get("/api/runs")
def runs() -> dict:
    return {"runs": db.list_runs()}


@app.post("/api/worker/run")
def worker_run() -> dict:
    return run_once("manual")


@app.post("/api/intake/run")
def run_intake() -> dict:
    return run_once("manual")


@app.post("/api/intake/{email_id}/complete")
def complete(email_id: str) -> dict:
    _email_or_404(email_id)
    db.set_status(email_id, "triaged")
    return {"email_id": email_id, "status": "triaged"}


@app.post("/api/classify")
def classify(payload: EmailIn) -> dict:
    if payload.email_id and not (payload.subject or payload.body):
        email = _email_or_404(payload.email_id)
    else:
        email = {
            "id": payload.email_id,
            "subject": payload.subject,
            "body": payload.body,
            "from_name": payload.from_name,
            "from_email": payload.from_email,
        }
    result = classify_email(email)
    return {
        "email_id": email.get("id"),
        "subject": email.get("subject"),
        "from_name": email.get("from_name"),
        "from_email": email.get("from_email"),
        **result.as_dict(),
    }


@app.post("/api/triage")
def create_triage(payload: TriageIn) -> dict:
    email = _email_or_404(payload.email_id)
    stored = save_classification(email, _classification(payload))
    return db.public_triage({**stored, "subject": email["subject"], "mailbox_name": email["from_name"], "from_email": email["from_email"], "body": email["body"], "received_at": email["received_at"]})


@app.get("/api/triage")
def triage_list() -> dict:
    return {"items": [db.public_triage(row) for row in db.list_triage()]}


@app.get("/api/triage/{triage_id}")
def triage_detail(triage_id: int) -> dict:
    row = db.get_triage(triage_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Triage record not found")
    return db.public_triage(row)


@app.post("/api/triage/{triage_id}/draft")
def edit_draft(triage_id: int, payload: DraftIn) -> dict:
    row = db.update_draft(triage_id, payload.draft_reply)
    if row is None:
        raise HTTPException(status_code=404, detail="Triage record not found")
    return db.public_triage(row)


@app.post("/api/triage/{triage_id}/approve")
def approve_reply(triage_id: int) -> dict:
    row = db.approve(triage_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Triage record not found")
    alerts.post_alert(
        row["category"],
        {
            "email_id": row["email_id"],
            "name": row["name"],
            "company": row["company"],
            "subject": row["subject"],
            "budget": row["budget"],
            "intent": row["intent"],
        },
        title="Reply approved",
        body=f"Approved reply for {row['name'] or row['mailbox_name'] or 'the sender'} — {row['subject']}",
    )
    return db.public_triage(row)


@app.post("/api/crm/leads")
def create_lead(payload: LeadIn) -> dict:
    email = db.get_email(payload.email_id)
    result = Classification(
        category=payload.category,
        confidence=1,
        name=payload.name,
        company=payload.company,
        budget=payload.budget,
        intent=payload.intent or "",
        draft_reply="",
        model="rules",
    )
    if email:
        result.name = payload.name
        stored = push_lead(
            {
                "id": payload.email_id,
                "from_email": payload.from_email or email.get("from_email"),
                "subject": payload.subject or email.get("subject"),
            },
            result,
        )
    else:
        stored = crm.store_lead(
            {
                "email_id": payload.email_id,
                "name": payload.name,
                "company": payload.company,
                "email": payload.from_email,
                "budget": payload.budget,
                "intent": payload.intent,
                "category": payload.category,
                "source_subject": payload.subject,
                "status": "Reply pending",
            }
        )
    return stored


@app.get("/api/crm/leads")
def leads() -> dict:
    return {"leads": db.list_leads()}


@app.post("/api/alerts")
def create_alert(payload: AlertIn) -> dict:
    return alerts.post_alert(
        payload.category,
        {
            "email_id": payload.email_id,
            "name": payload.name,
            "company": payload.company,
            "budget": payload.budget,
            "intent": payload.intent,
            "subject": payload.subject,
        },
        title=payload.title,
        body=payload.body,
    )


@app.get("/api/alerts")
def alert_feed() -> dict:
    return {"alerts": db.list_alerts()}


@app.post("/api/demo/reset")
def demo_reset() -> dict:
    count = reset_demo()
    return {"seeded": count}


@app.get("/")
def root() -> dict:
    return {"service": "lane-triage", "docs": "/docs", "health": "/api/health"}
