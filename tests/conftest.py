"""Shared API client. Mutations need a bearer token. The webhook needs an HMAC."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

TOKEN = "test-token"
SECRET = "test-hook"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "triage.db"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("HUBSPOT_TOKEN", raising=False)
    monkeypatch.delenv("GHL_API_KEY", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("IMAP_HOST", raising=False)
    monkeypatch.setenv("WORKER_ENABLED", "false")
    monkeypatch.setenv("API_TOKEN", TOKEN)
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("LLM_RETRY_BACKOFF", "0")
    from app.main import app

    with TestClient(app) as test_client:
        test_client.headers.update({"Authorization": f"Bearer {TOKEN}"})
        yield test_client


def signed_body(payload: dict) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(payload).encode()
    digest = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {
        "Content-Type": "application/json",
        "X-Lane-Signature": f"sha256={digest}",
    }
