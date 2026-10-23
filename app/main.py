"""HTTP API: webhook ingest, classification, and the desk the worker fills."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from contextlib import asynccontextmanager
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

load_dotenv()

from app import alerts, crm, db
from app.classifier import Classification
from app.llm import DEMO_LIMIT_NOTICE, classify_email, classify_for_visitor, select_provider
from app.mailbox import mailbox_mode
from app.gate import FilingBlocked, FilingConfirm, evaluate_filing
from app.pipeline import _known_contacts, accept_suggestion, push_lead, save_classification
from app.replay import apply_recording, recording_status
from app.db import AlreadyApproved, DraftLocked
from app.llm import anthropic_model
from app.seed import reset_demo, seed_if_empty
from app.worker import run_once, start_worker, status as worker_status, stop_worker

logger = logging.getLogger("lane")


class _RedactQuery(logging.Filter):
    """Drop query strings from the access log. Keys belong in X-Lane-Key, not the URL."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Uvicorn's access formatter unpacks a 5-tuple. Edit the path in place.
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str) and "?" in args[2]:
            path, _query = args[2].split("?", 1)
            record.args = (*args[:2], f"{path}?redacted", *args[3:])
        return True


logging.getLogger("uvicorn.access").addFilter(_RedactQuery())
BODY_LIMIT = 256 * 1024

MINUTES_PER_EMAIL = 6
PROJECTED_DAILY_VOLUME = 80


_DEMO_SECRETS = {"", "lane-demo-token", "lane-demo-webhook", "changeme", "secret", "password"}


def assert_runtime_secrets() -> None:
    """A non-demo process must not boot with the published sample secrets."""
    if _demo_enabled():
        return
    token = os.environ.get("API_TOKEN", "").strip()
    secret = os.environ.get("WEBHOOK_SECRET", "").strip()
    if token in _DEMO_SECRETS or secret in _DEMO_SECRETS or token == secret:
        raise RuntimeError("DEMO_MODE=false requires a unique API_TOKEN and WEBHOOK_SECRET")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    assert_runtime_secrets()
    db.init_db()
    seed_if_empty()
    start_worker()
    try:
        yield
    finally:
        stop_worker()


app = FastAPI(title="Relay inbox triage", version="1.0.0", lifespan=lifespan)


def _origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "http://127.0.0.1:8742,http://localhost:8742")
    return [item.strip() for item in raw.split(",") if item.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins(),
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-Lane-Signature"],
)


def _demo_enabled() -> bool:
    return os.environ.get("DEMO_MODE", "true").strip().lower() in {"1", "true", "yes"}


def _authorized(request: Request) -> bool:
    token = os.environ.get("API_TOKEN", "").strip()
    header = request.headers.get("authorization", "")
    if not token or not header.lower().startswith("bearer "):
        return False
    presented = header.split(" ", 1)[1].strip()
    return hmac.compare_digest(presented, token)


def _needs_token(request: Request) -> bool:
    path = request.url.path
    if path.startswith("/api/webhooks/"):
        return False
    if request.method != "GET":
        return True
    return path.startswith(
        ("/api/triage", "/api/crm", "/api/alerts", "/api/intake", "/api/runs", "/api/stats", "/api/worker")
    )


@app.middleware("http")
async def guard(request: Request, call_next):
    # Browsers send OPTIONS without the bearer token. CORS answers it.
    if request.method == "OPTIONS":
        return await call_next(request)
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > BODY_LIMIT:
        return JSONResponse({"detail": "payload too large"}, status_code=413)
    if request.method in {"POST", "PUT", "PATCH"}:
        body = await request.body()
        if len(body) > BODY_LIMIT:
            return JSONResponse({"detail": "payload too large"}, status_code=413)

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request(request.scope, receive)
    if _needs_token(request) and not _authorized(request):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


class EmailIn(BaseModel):
    email_id: str | None = None
    subject: str = ""
    body: str = ""
    from_name: str = ""
    from_email: str = ""


class TriageIn(BaseModel):
    email_id: str
    category: Literal["lead", "support", "invoice", "spam", "urgent", "suspicious", "review", "recruiter"]
    confidence: float = Field(ge=0, le=1)
    name: str | None = None
    company: str | None = None
    budget: str | None = None
    intent: str
    draft_reply: str
    model: str = "rules"


class DraftIn(BaseModel):
    draft_reply: str = Field(min_length=1)


class AcceptIn(BaseModel):
    category: Literal["lead", "support", "invoice", "spam", "urgent", "suspicious", "recruiter"] | None = None
    confirm: bool = False


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
    in_reply_to: str | None = None
    references: str | None = None
    headers: dict[str, str | list[str]] | None = None


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
        "fallbacks": db.count_fallbacks(),
        "anthropic_model": anthropic_model(),
    }


@app.get("/api/stats")
def stats() -> dict:
    emails = db.list_emails()
    triage = db.list_triage(limit=None)
    leads = db.list_leads()
    by_category = {name: 0 for name in ("lead", "support", "invoice", "spam", "urgent", "suspicious", "review", "recruiter")}
    approved = 0
    for item in triage:
        by_category[item["category"]] = by_category.get(item["category"], 0) + 1
        if item["approved"]:
            approved += 1
    actionable = [item for item in triage if item["category"] not in {"spam", "suspicious", "review", "recruiter"}]
    processed = len(triage)
    actionable_count = len(actionable)
    approved = sum(1 for item in actionable if item["approved"])
    return {
        "processed": processed,
        "waiting": sum(1 for email in emails if email["status"] == "new"),
        "pending_approval": actionable_count - approved,
        "approved": approved,
        "leads": len(leads),
        "alerts": len(db.list_alerts()),
        "by_category": by_category,
        "hours_saved": round(actionable_count * MINUTES_PER_EMAIL / 60, 1),
        "hours_saved_note": "Spam, suspicious, and needs-review mail are not counted. The daily figure is an assumption, not a measurement.",
        "minutes_per_email": MINUTES_PER_EMAIL,
        "projected_daily_hours": round(PROJECTED_DAILY_VOLUME * MINUTES_PER_EMAIL / 60, 1),
        "projected_daily_volume": PROJECTED_DAILY_VOLUME,
        "fallbacks": db.count_fallbacks(),
        "mode": select_provider(),
        "mailbox": mailbox_mode(),
        "crm": crm.destination_label(),
    }


@app.get("/api/intake/pending")
def pending() -> dict:
    return {"emails": db.list_emails(status="new")}


def _identity(payload: WebhookEmail) -> str:
    if payload.message_id and payload.message_id.strip():
        return payload.message_id.strip()
    raw = "|".join(
        [
            payload.from_email,
            payload.subject,
            payload.received_at or "",
            payload.body[:2000],
        ]
    )
    return "wh-" + hashlib.sha256(raw.encode()).hexdigest()[:20]


def _signature_ok(raw: bytes, header: str) -> bool:
    secret = os.environ.get("WEBHOOK_SECRET", "").strip()
    if not secret or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header, expected)


@app.post("/api/webhooks/email")
async def ingest_email(request: Request) -> dict:
    """Inbound mail. The body must be signed with WEBHOOK_SECRET."""
    raw = await request.body()
    if not _signature_ok(raw, request.headers.get("x-lane-signature", "")):
        raise HTTPException(status_code=401, detail="invalid webhook signature")
    try:
        payload = WebhookEmail.model_validate_json(raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="invalid webhook body") from exc
    email_id = _identity(payload)
    if db.get_email(email_id):
        return {"id": email_id, "status": "duplicate"}
    db.insert_email(
        {
            "id": email_id,
            "message_id": (payload.message_id or "").strip(),
            "from_name": payload.from_name,
            "from_email": payload.from_email,
            "subject": payload.subject,
            "body": payload.body,
            "received_at": payload.received_at or db.now(),
            "in_reply_to": payload.in_reply_to or "",
            "references": payload.references or "",
            "headers": payload.headers or {},
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


def _visitor_credentials(request: Request) -> tuple[str, str | None]:
    """The visitor key stays on this request. It is not logged or stored."""
    secret = (request.headers.get("x-lane-key") or "").strip()
    hint = (request.headers.get("x-lane-provider") or "").strip().lower() or None
    if hint not in {None, "anthropic", "openai"}:
        hint = None
    return secret, hint


@app.post("/api/classify")
def classify(payload: EmailIn, request: Request) -> dict:
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
    secret, hint = _visitor_credentials(request)
    if not (payload.subject or payload.body or "").strip() and not payload.email_id and not secret:
        return {
            "email_id": payload.email_id,
            "subject": payload.subject,
            "from_name": payload.from_name,
            "from_email": payload.from_email,
            "category": "review",
            "confidence": 0.35,
            "name": None,
            "company": None,
            "budget": None,
            "intent": "review a message",
            "draft_reply": DEMO_LIMIT_NOTICE,
            "model": "rules",
            "mode": "demo",
            "notice": DEMO_LIMIT_NOTICE,
        }
    if secret:
        outcome = classify_for_visitor(email, secret, hint)
        return {
            "email_id": email.get("id"),
            "subject": email.get("subject"),
            "from_name": email.get("from_name"),
            "from_email": email.get("from_email"),
            "mode": outcome.mode,
            "notice": outcome.notice,
            **outcome.result.as_dict(),
        }
    result = classify_email(email)
    return {
        "email_id": email.get("id"),
        "subject": email.get("subject"),
        "from_name": email.get("from_name"),
        "from_email": email.get("from_email"),
        **result.as_dict(),
    }


@app.post("/api/triage/{triage_id}/live")
def live_pass(triage_id: int, request: Request) -> dict:
    """Reclassify one stored message with a key that is not kept after the call."""
    row = db.get_triage(triage_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Triage record not found")
    if row["approved"]:
        raise HTTPException(status_code=409, detail="already approved")
    secret, hint = _visitor_credentials(request)
    if not secret:
        raise HTTPException(
            status_code=400,
            detail="Add an API key to run live AI. Demo mode is still available.",
        )
    email = _email_or_404(row["email_id"])
    outcome = classify_for_visitor(email, secret, hint)
    if outcome.mode != "demo":
        save_classification(email, outcome.result)
        refreshed = db.get_triage(triage_id)
        row = refreshed or row
    return {
        "triage": db.public_triage(row, full_body=True),
        "mode": outcome.mode,
        "notice": outcome.notice,
    }


@app.post("/api/triage")
def create_triage(payload: TriageIn) -> dict:
    email = _email_or_404(payload.email_id)
    existing = db.get_triage_by_email(payload.email_id)
    if existing and existing["approved"]:
        raise HTTPException(status_code=409, detail="already approved")
    if existing and (existing.get("category") or "").strip().lower() == "suspicious":
        if payload.category != "suspicious":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "suspicious",
                    "message": "blocked: a suspicious message cannot be filed as a lead",
                    "reasons": ["category is suspicious"],
                },
            )
    if payload.category == "lead" and payment_related_message(email):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "payment",
                "message": "payment-related: verify by phone",
                "reasons": ["payment-related: verify by phone"],
            },
        )
    if payload.category == "lead":
        blocking = security_flags(email)
        if blocking:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "security",
                    "message": "blocked: verify by phone or security review",
                    "reasons": blocking,
                },
            )
    stored = save_classification(email, _classification(payload))
    return db.public_triage(
        {**stored, "subject": email["subject"], "mailbox_name": email["from_name"], "from_email": email["from_email"], "body": email["body"], "received_at": email["received_at"]},
        full_body=True,
    )


@app.get("/api/triage")
def triage_list(limit: int = 50, offset: int = 0) -> dict:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    return {"items": [db.public_triage(row) for row in db.list_triage(limit=limit, offset=offset)]}


@app.get("/api/triage/{triage_id}")
def triage_detail(triage_id: int) -> dict:
    row = db.get_triage(triage_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Triage record not found")
    return db.public_triage(row, full_body=True)


@app.post("/api/triage/{triage_id}/draft")
def edit_draft(triage_id: int, payload: DraftIn) -> dict:
    try:
        row = db.update_draft(triage_id, payload.draft_reply)
    except DraftLocked as exc:
        logger.warning("edited after approval triage_id=%s", triage_id)
        raise HTTPException(status_code=409, detail="edited after approval") from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Triage record not found")
    return db.public_triage(row, full_body=True)


@app.post("/api/triage/{triage_id}/approve")
def approve_reply(triage_id: int) -> dict:
    row = db.get_triage(triage_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Triage record not found")
    if row["approved"]:
        raise HTTPException(status_code=409, detail="already approved")
    # Approving a lead files it. A confirm or a block does not lock the reply.
    if (row.get("category") or "") == "lead":
        try:
            accept_suggestion(row, "lead", confirmed=False)
        except FilingConfirm as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "confirm", "message": exc.message, "reasons": exc.reasons},
            ) from exc
        except FilingBlocked as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message, "reasons": exc.reasons},
            ) from exc
    try:
        row = db.approve(triage_id)
    except AlreadyApproved as exc:
        raise HTTPException(status_code=409, detail="already approved") from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Triage record not found")
    # Approving a suspicious row archives it. It does not announce a reply.
    if row["category"] != "suspicious":
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
    return db.public_triage(row, full_body=True)


@app.post("/api/triage/{triage_id}/accept")
def accept_label(triage_id: int, payload: AcceptIn | None = None) -> dict:
    """Apply the reviewer's label. The filing gate, not this handler, decides."""
    row = db.get_triage(triage_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Triage record not found")
    incoming = payload or AcceptIn()
    try:
        outcome = accept_suggestion(row, incoming.category, confirmed=incoming.confirm)
    except AlreadyApproved as exc:
        raise HTTPException(status_code=409, detail="already approved") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="no suggested label") from exc
    except FilingConfirm as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "confirm", "message": exc.message, "reasons": exc.reasons},
        ) from exc
    except FilingBlocked as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message, "reasons": exc.reasons},
        ) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Triage record not found") from exc
    return outcome["triage"]


def payment_related_message(email: dict) -> bool:
    from app.gate import _readable
    from app.risk import payment_related

    return payment_related(_readable(email))


def security_flags(email: dict) -> list[str]:
    """Hard flags on the stored message. A lead label cannot be written over them."""
    from app.gate import _readable
    from app.risk import assess_risk, hard_flags

    readable = _readable(email)
    return hard_flags(assess_risk(email, readable, email.get("body") or ""))


@app.post("/api/crm/leads")
def create_lead(payload: LeadIn) -> dict:
    """Every CRM write is a lead write, and the filing gate runs on the message."""
    email = db.get_email(payload.email_id)
    if email is None:
        raise HTTPException(status_code=404, detail=f"No message {payload.email_id}")
    stored_triage = db.get_triage_by_email(payload.email_id)
    current = (stored_triage or {}).get("category") or "lead"
    try:
        evaluate_filing(
            email,
            current_category=current,
            target="lead",
            known_contacts=_known_contacts(),
            confirmed=False,
        ).raise_if_refused()
    except FilingBlocked as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message, "reasons": exc.reasons},
        ) from exc
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
    result.name = payload.name
    return push_lead(
        {
            "id": payload.email_id,
            "from_email": payload.from_email or email.get("from_email"),
            "subject": payload.subject or email.get("subject"),
        },
        result,
    )


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


@app.get("/api/demo/recording")
def demo_recording() -> dict:
    if not _demo_enabled():
        raise HTTPException(status_code=404, detail="not found")
    return recording_status()


@app.post("/api/demo/replay")
def demo_replay() -> dict:
    """Apply a recorded Claude pass. Refuses to invent one when the file is missing."""
    if not _demo_enabled():
        raise HTTPException(status_code=404, detail="not found")
    try:
        return apply_recording()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Recorded Claude pass: no recording yet") from exc


@app.post("/api/demo/reset")
def demo_reset() -> dict:
    if not _demo_enabled():
        raise HTTPException(status_code=404, detail="not found")
    if os.environ.get("IMAP_HOST", "").strip():
        raise HTTPException(status_code=409, detail="reset is disabled while IMAP is configured")
    count = reset_demo()
    return {"seeded": count}


@app.get("/")
def root() -> dict:
    return {"service": "lane-triage", "docs": "/docs", "health": "/api/health"}
