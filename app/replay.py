"""Replay a Claude pass that was recorded from the API.

The JSON is produced by `python -m evals.live_claude --record demo/recorded_pass.json`.
This module never invents a pass. If the file is missing, the desk says so.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app import db

_KIND = "recorded-claude-pass"


def recording_path() -> Path:
    override = os.environ.get("LANE_RECORDED_PASS", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1] / "demo" / "recorded_pass.json"


def _empty() -> dict:
    return {"present": False, "label": "Recorded Claude pass: no recording yet"}


def load_recording() -> dict | None:
    path = recording_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("kind") != _KIND or not isinstance(data.get("rows"), list):
        return None
    return data


def recording_status() -> dict:
    data = load_recording()
    if data is None:
        return _empty()
    recorded_at = str(data.get("recorded_at") or "")
    date = recorded_at[:10] if len(recorded_at) >= 10 else "undated"
    model = str(data.get("model") or "unknown model")
    mailbox = str(data.get("mailbox") or "sample mailbox")
    return {
        "present": True,
        "label": f"Recorded Claude pass, {date}, {model}, {mailbox}",
        "recorded_at": recorded_at,
        "model": model,
        "mailbox": mailbox,
        "count": len(data["rows"]),
    }


def apply_recording() -> dict:
    """Copy the recorded rows onto sample messages that are already in the mailbox."""
    data = load_recording()
    if data is None:
        raise FileNotFoundError("Recorded Claude pass: no recording yet")
    applied = 0
    for row in data["rows"]:
        if not isinstance(row, dict):
            continue
        email_id = str(row.get("id") or "")
        category = row.get("category")
        if not email_id or not category or db.get_email(email_id) is None:
            continue
        db.save_triage(
            email_id,
            {
                "category": category,
                "confidence": float(row.get("confidence") or 0.5),
                "name": row.get("name"),
                "company": row.get("company"),
                "budget": row.get("budget"),
                "intent": row.get("intent") or "",
                "draft_reply": row.get("draft_reply") or "",
                "model": row.get("model") or data.get("model") or "claude-sonnet-5-5",
                "risk_flags": row.get("risk_flags") or [],
                "secondary_categories": row.get("secondary_categories") or [],
                "suggested_category": row.get("suggested_category"),
                "suggestion_confidence": row.get("suggestion_confidence"),
                "reasons": row.get("reasons") or [],
            },
        )
        applied += 1
    status = recording_status()
    status["applied"] = applied
    return status
