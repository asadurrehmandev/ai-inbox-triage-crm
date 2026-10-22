"""SQLite storage for the mailbox, triage decisions, CRM, and alerts."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

_LOCK = threading.RLock()
_CONN: sqlite3.Connection | None = None
_CONN_PATH: str | None = None

BODY_PREVIEW = 500


class DraftLocked(Exception):
    """An approved reply cannot be edited in place."""


class AlreadyApproved(Exception):
    """Approve was already recorded for this triage row."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS emails (
  id TEXT PRIMARY KEY,
  from_name TEXT,
  from_email TEXT,
  subject TEXT,
  body TEXT,
  received_at TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  message_id TEXT NOT NULL DEFAULT '',
  in_reply_to TEXT NOT NULL DEFAULT '',
  references_header TEXT NOT NULL DEFAULT '',
  headers TEXT NOT NULL DEFAULT '',
  dkim_verified TEXT NOT NULL DEFAULT ''
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
  created_at TEXT NOT NULL,
  risk_flags TEXT NOT NULL DEFAULT '',
  secondary_categories TEXT NOT NULL DEFAULT '',
  llm_error TEXT,
  forwarded_by TEXT,
  suggested_category TEXT,
  suggestion_confidence REAL,
  reasons TEXT NOT NULL DEFAULT '[]'
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
  created_at TEXT NOT NULL,
  remote_status TEXT NOT NULL DEFAULT '',
  remote_error TEXT
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

CREATE TABLE IF NOT EXISTS worker_lock (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  owner TEXT NOT NULL DEFAULT '',
  expires_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS filing_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email_id TEXT NOT NULL,
  action TEXT NOT NULL,
  reasons TEXT NOT NULL,
  created_at TEXT NOT NULL
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
    """One connection per process. WAL and the lock keep workers from trampling it."""
    global _CONN, _CONN_PATH
    path = database_path()
    if _CONN is not None and _CONN_PATH == str(path):
        return _CONN
    if _CONN is not None:
        _CONN.close()
        _CONN = None
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _CONN = conn
    _CONN_PATH = str(path)
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def init_db() -> None:
    with _LOCK, connect() as conn:
        conn.executescript(SCHEMA)
        for column, ddl in (
            ("risk_flags", "TEXT NOT NULL DEFAULT ''"),
            ("secondary_categories", "TEXT NOT NULL DEFAULT ''"),
            ("llm_error", "TEXT"),
            ("forwarded_by", "TEXT"),
            ("suggested_category", "TEXT"),
            ("suggestion_confidence", "REAL"),
            ("reasons", "TEXT NOT NULL DEFAULT '[]'"),
        ):
            if column not in _columns(conn, "triage"):
                conn.execute(f"ALTER TABLE triage ADD COLUMN {column} {ddl}")
        for column, ddl in (
            ("remote_status", "TEXT NOT NULL DEFAULT ''"),
            ("remote_error", "TEXT"),
        ):
            if column not in _columns(conn, "leads"):
                conn.execute(f"ALTER TABLE leads ADD COLUMN {column} {ddl}")
        for column, ddl in (
            ("message_id", "TEXT NOT NULL DEFAULT ''"),
            ("in_reply_to", "TEXT NOT NULL DEFAULT ''"),
            ("references_header", "TEXT NOT NULL DEFAULT ''"),
            ("headers", "TEXT NOT NULL DEFAULT ''"),
            ("dkim_verified", "TEXT NOT NULL DEFAULT ''"),
        ):
            if column not in _columns(conn, "emails"):
                conn.execute(f"ALTER TABLE emails ADD COLUMN {column} {ddl}")


def _rows(query: str, params: tuple = ()) -> list[dict]:
    with _LOCK, connect() as conn:
        found = conn.execute(query, params).fetchall()
    return [dict(row) for row in found]


def _one(query: str, params: tuple = ()) -> dict | None:
    rows = _rows(query, params)
    return rows[0] if rows else None


def _header_blob(email: dict) -> str:
    raw = email.get("headers") or ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        return json.dumps(raw)
    return ""


def insert_email(email: dict) -> None:
    headers = email.get("headers") if isinstance(email.get("headers"), dict) else {}
    in_reply_to = email.get("in_reply_to") or headers.get("In-Reply-To") or headers.get("in-reply-to") or ""
    references = (
        email.get("references")
        or email.get("references_header")
        or headers.get("References")
        or headers.get("references")
        or ""
    )
    if isinstance(in_reply_to, list):
        in_reply_to = " ".join(str(item) for item in in_reply_to)
    if isinstance(references, list):
        references = " ".join(str(item) for item in references)
    # Only a local DKIM check may set this. A webhook payload cannot.
    verified = ""
    if email.get("dkim_verified_source") == "local":
        verified = str(email.get("dkim_verified") or "")
    with _LOCK, connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO emails
            (id, from_name, from_email, subject, body, received_at, status,
             message_id, in_reply_to, references_header, headers, dkim_verified)
            VALUES (?, ?, ?, ?, ?, ?, 'new', ?, ?, ?, ?, ?)
            """,
            (
                email["id"],
                email.get("from_name"),
                email.get("from_email"),
                email.get("subject"),
                email.get("body"),
                email.get("received_at"),
                email.get("message_id") or "",
                str(in_reply_to or ""),
                str(references or ""),
                _header_blob(email),
                verified,
            ),
        )


def thread_participants(message_ids: list[str], *, exclude_id: str = "") -> list[str]:
    """From addresses of messages Lane has stored under these Message-IDs."""
    cleaned: list[str] = []
    for item in message_ids:
        token = str(item or "").strip().strip("<>")
        if token and token not in cleaned:
            cleaned.append(token)
    if not cleaned:
        return []
    marks = ",".join("?" * len(cleaned))
    rows = _rows(
        f"""
        SELECT id, from_email FROM emails
        WHERE id IN ({marks}) OR message_id IN ({marks})
        """,
        tuple([*cleaned, *cleaned]),
    )
    found: list[str] = []
    for row in rows:
        if exclude_id and row.get("id") == exclude_id:
            continue
        address = (row.get("from_email") or "").strip().lower()
        if address and address not in found:
            found.append(address)
    return found


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


def _csv(value: object) -> str:
    if isinstance(value, list):
        return ",".join(str(item) for item in value if item)
    return str(value or "")


def save_triage(email_id: str, result: dict, force: bool = False) -> dict:
    with _LOCK, connect() as conn:
        existing = conn.execute(
            "SELECT approved FROM triage WHERE email_id = ?",
            (email_id,),
        ).fetchone()
        if existing and existing["approved"] and not force:
            locked = True
        else:
            locked = False
            conn.execute(
            """
            INSERT INTO triage (
              email_id, category, confidence, name, company, budget, intent,
              draft_reply, model, approved, edited, created_at,
              risk_flags, secondary_categories, llm_error, forwarded_by,
              suggested_category, suggestion_confidence, reasons
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(email_id) DO UPDATE SET
              category = excluded.category,
              confidence = excluded.confidence,
              name = excluded.name,
              company = excluded.company,
              budget = excluded.budget,
              intent = excluded.intent,
              draft_reply = excluded.draft_reply,
              model = excluded.model,
              risk_flags = excluded.risk_flags,
              secondary_categories = excluded.secondary_categories,
              llm_error = excluded.llm_error,
              forwarded_by = excluded.forwarded_by,
              suggested_category = excluded.suggested_category,
              suggestion_confidence = excluded.suggestion_confidence,
              reasons = excluded.reasons
            WHERE triage.approved = 0
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
                _csv(result.get("risk_flags")),
                _csv(result.get("secondary_categories")),
                result.get("llm_error"),
                result.get("forwarded_by"),
                result.get("suggested_category"),
                result.get("suggestion_confidence"),
                json.dumps(result.get("reasons") or []),
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


def list_triage(limit: int | None = 50, offset: int = 0) -> list[dict]:
    query = """
        SELECT t.*, e.subject, e.from_name AS mailbox_name, e.from_email,
               e.body, e.received_at, e.status AS email_status
        FROM triage t
        JOIN emails e ON e.id = t.email_id
        ORDER BY e.received_at DESC
    """
    if limit is None:
        return _rows(query)
    return _rows(query + " LIMIT ? OFFSET ?", (limit, offset))


def get_triage(triage_id: int) -> dict | None:
    return _one(
        """
        SELECT t.*, e.subject, e.from_name AS mailbox_name, e.from_email,
               e.body, e.received_at, e.status AS email_status,
               e.message_id, e.in_reply_to, e.references_header, e.headers,
               e.dkim_verified
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
        row = conn.execute("SELECT approved FROM triage WHERE id = ?", (triage_id,)).fetchone()
        if row is None:
            return None
        if row["approved"]:
            raise DraftLocked(triage_id)
        conn.execute(
            "UPDATE triage SET draft_reply = ?, edited = 1 WHERE id = ?",
            (draft_reply, triage_id),
        )
    return get_triage(triage_id)


def approve(triage_id: int) -> dict | None:
    with _LOCK, connect() as conn:
        row = conn.execute("SELECT approved, email_id FROM triage WHERE id = ?", (triage_id,)).fetchone()
        if row is None:
            return None
        if row["approved"]:
            raise AlreadyApproved(triage_id)
        conn.execute("UPDATE triage SET approved = 1 WHERE id = ?", (triage_id,))
        row = conn.execute("SELECT email_id FROM triage WHERE id = ?", (triage_id,)).fetchone()
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
              source_subject, status, destination, created_at, remote_status, remote_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(email_id) DO UPDATE SET
              name = excluded.name,
              company = excluded.company,
              email = excluded.email,
              budget = excluded.budget,
              intent = excluded.intent,
              category = excluded.category,
              source_subject = excluded.source_subject,
              destination = excluded.destination,
              remote_status = excluded.remote_status,
              remote_error = excluded.remote_error
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
                lead.get("destination", "mock"),
                now(),
                lead.get("remote_status", ""),
                lead.get("remote_error"),
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
        conn.execute("DELETE FROM filing_log")


def insert_filing_log(email_id: str, action: str, reasons: list[str]) -> None:
    with _LOCK, connect() as conn:
        conn.execute(
            "INSERT INTO filing_log (email_id, action, reasons, created_at) VALUES (?, ?, ?, ?)",
            (email_id, action, json.dumps(reasons), now()),
        )


def list_filing_log() -> list[dict]:
    rows = _rows("SELECT * FROM filing_log ORDER BY id")
    for row in rows:
        try:
            row["reasons"] = json.loads(row.get("reasons") or "[]")
        except json.JSONDecodeError:
            row["reasons"] = []
    return rows


def count_fallbacks() -> int:
    row = _one("SELECT COUNT(*) AS n FROM triage WHERE model = 'rules-fallback'")
    return int(row["n"]) if row else 0


def acquire_worker_lock(owner: str, ttl_seconds: int = 180) -> bool:
    expires = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).replace(microsecond=0).isoformat()
    with _LOCK:
        conn = connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("INSERT OR IGNORE INTO worker_lock (id, owner, expires_at) VALUES (1, '', '')")
            current = conn.execute("SELECT owner, expires_at FROM worker_lock WHERE id = 1").fetchone()
            free = (
                current is None
                or not current["owner"]
                or current["owner"] == owner
                or (current["expires_at"] or "") < now()
            )
            if not free:
                conn.rollback()
                return False
            conn.execute(
                "UPDATE worker_lock SET owner = ?, expires_at = ? WHERE id = 1",
                (owner, expires),
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise


def release_worker_lock(owner: str) -> None:
    with _LOCK, connect() as conn:
        conn.execute(
            "UPDATE worker_lock SET owner = '', expires_at = '' WHERE id = 1 AND owner = ?",
            (owner,),
        )


def public_triage(row: dict, full_body: bool = False) -> dict:
    body = row.get("body") or ""
    if not full_body and len(body) > BODY_PREVIEW:
        body = body[:BODY_PREVIEW]
    flags = [item for item in (row.get("risk_flags") or "").split(",") if item]
    secondary = [item for item in (row.get("secondary_categories") or "").split(",") if item]
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
        "from_name": row.get("mailbox_name") or row.get("from_name"),
        "from_email": row.get("from_email"),
        "body": body,
        "received_at": row.get("received_at"),
        "risk_flags": flags,
        "secondary_categories": secondary,
        "llm_error": row.get("llm_error"),
        "forwarded_by": row.get("forwarded_by"),
        "suggested_category": row.get("suggested_category") or None,
        "suggestion_confidence": row.get("suggestion_confidence"),
        "reasons": _reasons(row.get("reasons")),
    }


def _reasons(raw: object) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw]
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return [str(raw)]
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return []


def accept_category(triage_id: int, category: str, confidence: float) -> dict | None:
    """Record the reviewer's one-click label. An approved row is left alone."""
    with _LOCK, connect() as conn:
        row = conn.execute("SELECT approved FROM triage WHERE id = ?", (triage_id,)).fetchone()
        if row is None:
            return None
        if row["approved"]:
            raise AlreadyApproved(triage_id)
        conn.execute(
            "UPDATE triage SET category = ?, confidence = ? WHERE id = ?",
            (category, confidence, triage_id),
        )
    return get_triage(triage_id)
