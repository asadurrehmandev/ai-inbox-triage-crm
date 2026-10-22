"""SQLite storage for the mailbox, triage decisions, CRM, and alerts."""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS emails (
  id TEXT PRIMARY KEY,
  from_name TEXT,
  from_email TEXT,
  subject TEXT,
  body TEXT,
  received_at TEXT,
  status TEXT NOT NULL DEFAULT 'new'
);

CREATE TABLE IF NOT EXISTS triage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email_id TEXT UNIQUE,
  category TEXT NOT NULL,
  confidence REAL NOT NULL,
  name TEXT,
  company TEXT,
  budget TEXT,
  intent TEXT,
  draft_reply TEXT NOT NULL,
  model TEXT NOT NULL,
  approved INTEGER NOT NULL DEFAULT 0,
  edited INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email_id TEXT UNIQUE,
  name TEXT,
  company TEXT,
  email TEXT,
  budget TEXT,
  intent TEXT,
  category TEXT,
  source_subject TEXT,
  status TEXT NOT NULL,
  destination TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email_id TEXT,
  category TEXT,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL,
  processed INTEGER NOT NULL,
  leads INTEGER NOT NULL,
  alerts INTEGER NOT NULL,
  ingested INTEGER NOT NULL DEFAULT 0
);
"""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def database_path() -> Path:
    raw = os.environ.get("DATABASE_PATH", "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[1] / "data" / "triage.db"


def connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _LOCK, connect() as conn:
        conn.executescript(SCHEMA)


def _rows(query: str, params: tuple = ()) -> list[dict]:
    with _LOCK, connect() as conn:
        found = conn.execute(query, params).fetchall()
    return [dict(row) for row in found]


def _one(query: str, params: tuple = ()) -> dict | None:
    rows = _rows(query, params)
    return rows[0] if rows else None


def insert_email(email: dict) -> None:
    with _LOCK, connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO emails
            (id, from_name, from_email, subject, body, received_at, status)
            VALUES (?, ?, ?, ?, ?, ?, 'new')
            """,
            (
                email["id"],
                email.get("from_name"),
                email.get("from_email"),
                email.get("subject"),
                email.get("body"),
                email.get("received_at"),
            ),
        )


def list_emails(status: str | None = None) -> list[dict]:
    if status:
        return _rows(
            "SELECT * FROM emails WHERE status = ? ORDER BY received_at DESC",
            (status,),
        )
    return _rows("SELECT * FROM emails ORDER BY received_at DESC")


def get_email(email_id: str) -> dict | None:
    return _one("SELECT * FROM emails WHERE id = ?", (email_id,))


def email_count() -> int:
    row = _one("SELECT COUNT(*) AS n FROM emails")
    return int(row["n"]) if row else 0


def set_status(email_id: str, status: str) -> None:
    with _LOCK, connect() as conn:
        conn.execute("UPDATE emails SET status = ? WHERE id = ?", (status, email_id))


def save_triage(email_id: str, result: dict) -> dict:
    with _LOCK, connect() as conn:
        conn.execute(
            """
            INSERT INTO triage (
              email_id, category, confidence, name, company, budget, intent,
              draft_reply, model, approved, edited, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
            ON CONFLICT(email_id) DO UPDATE SET
              category = excluded.category,
              confidence = excluded.confidence,
              name = excluded.name,
              company = excluded.company,
              budget = excluded.budget,
              intent = excluded.intent,
              draft_reply = excluded.draft_reply,
              model = excluded.model
            """,
            (
                email_id,
                result["category"],
                result["confidence"],
                result.get("name"),
                result.get("company"),
                result.get("budget"),
                result.get("intent"),
                result["draft_reply"],
                result.get("model", "rules"),
                now(),
            ),
        )
        conn.execute(
            "UPDATE emails SET status = 'triaged' WHERE id = ?",
            (email_id,),
        )
    found = get_triage_by_email(email_id)
    if found is None:
        raise RuntimeError(f"Triage for {email_id} was not stored")
    return found


def list_triage() -> list[dict]:
    return _rows(
        """
        SELECT t.*, e.subject, e.from_name AS mailbox_name, e.from_email,
               e.body, e.received_at, e.status AS email_status
        FROM triage t
        JOIN emails e ON e.id = t.email_id
        ORDER BY e.received_at DESC
        """
    )


def get_triage(triage_id: int) -> dict | None:
    return _one(
        """
        SELECT t.*, e.subject, e.from_name AS mailbox_name, e.from_email,
               e.body, e.received_at, e.status AS email_status
        FROM triage t
        JOIN emails e ON e.id = t.email_id
        WHERE t.id = ?
        """,
        (triage_id,),
    )


def get_triage_by_email(email_id: str) -> dict | None:
    return _one("SELECT * FROM triage WHERE email_id = ?", (email_id,))


def update_draft(triage_id: int, draft_reply: str) -> dict | None:
    with _LOCK, connect() as conn:
        conn.execute(
            "UPDATE triage SET draft_reply = ?, edited = 1 WHERE id = ?",
            (draft_reply, triage_id),
        )
    return get_triage(triage_id)


def approve(triage_id: int) -> dict | None:
    with _LOCK, connect() as conn:
        conn.execute("UPDATE triage SET approved = 1 WHERE id = ?", (triage_id,))
        row = conn.execute("SELECT email_id FROM triage WHERE id = ?", (triage_id,)).fetchone()
        if row:
            conn.execute(
                "UPDATE leads SET status = 'Reply approved' WHERE email_id = ?",
                (row["email_id"],),
            )
    return get_triage(triage_id)


def upsert_lead(lead: dict) -> dict:
    with _LOCK, connect() as conn:
        conn.execute(
            """
            INSERT INTO leads (
              email_id, name, company, email, budget, intent, category,
              source_subject, status, destination, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(email_id) DO UPDATE SET
              name = excluded.name,
              company = excluded.company,
              email = excluded.email,
              budget = excluded.budget,
              intent = excluded.intent,
              category = excluded.category,
              source_subject = excluded.source_subject,
              destination = excluded.destination
            """,
            (
                lead["email_id"],
                lead.get("name"),
                lead.get("company"),
                lead.get("email"),
                lead.get("budget"),
                lead.get("intent"),
                lead.get("category", "lead"),
                lead.get("source_subject"),
                lead.get("status", "Reply pending"),
                lead.get("destination", "sqlite"),
                now(),
            ),
        )
    found = _one("SELECT * FROM leads WHERE email_id = ?", (lead["email_id"],))
    if found is None:
        raise RuntimeError("Lead was not stored")
    return found


def list_leads() -> list[dict]:
    return _rows("SELECT * FROM leads ORDER BY created_at DESC")


def insert_alert(alert: dict) -> dict:
    with _LOCK, connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO alerts (email_id, category, title, body, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                alert.get("email_id"),
                alert.get("category"),
                alert["title"],
                alert["body"],
                now(),
            ),
        )
        alert_id = cursor.lastrowid
    found = _one("SELECT * FROM alerts WHERE id = ?", (alert_id,))
    if found is None:
        raise RuntimeError("Alert was not stored")
    return found


def list_alerts() -> list[dict]:
    return _rows("SELECT * FROM alerts ORDER BY id DESC")


def insert_run(run: dict) -> dict:
    with _LOCK, connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO runs (
              source, started_at, finished_at, processed, leads, alerts, ingested
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run["source"],
                run["started_at"],
                run["finished_at"],
                run["processed"],
                run["leads"],
                run["alerts"],
                run.get("ingested", 0),
            ),
        )
        run_id = cursor.lastrowid
    found = _one("SELECT * FROM runs WHERE id = ?", (run_id,))
    if found is None:
        raise RuntimeError("Run was not stored")
    return found


def list_runs(limit: int = 20) -> list[dict]:
    return _rows("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))


def latest_run() -> dict | None:
    return _one("SELECT * FROM runs ORDER BY id DESC LIMIT 1")


def clear_all() -> None:
    with _LOCK, connect() as conn:
        conn.execute("DELETE FROM runs")
        conn.execute("DELETE FROM alerts")
        conn.execute("DELETE FROM leads")
        conn.execute("DELETE FROM triage")
        conn.execute("DELETE FROM emails")


def public_triage(row: dict) -> dict:
    return {
        "id": row["id"],
        "email_id": row["email_id"],
        "category": row["category"],
        "confidence": row["confidence"],
        "name": row["name"],
        "company": row["company"],
        "budget": row["budget"],
        "intent": row["intent"],
        "draft_reply": row["draft_reply"],
        "model": row["model"],
        "approved": bool(row["approved"]),
        "edited": bool(row["edited"]),
        "created_at": row["created_at"],
        "subject": row.get("subject"),
        "from_name": row.get("mailbox_name"),
        "from_email": row.get("from_email"),
        "body": row.get("body"),
        "received_at": row.get("received_at"),
    }
