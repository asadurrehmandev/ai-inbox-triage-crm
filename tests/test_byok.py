"""A visitor key is used for one call and then gone.

It must not show up in the response, the logs, the database, or any file.
"""

import logging
import os
import uuid
from pathlib import Path

import httpx

from app.llm import KEY_QUOTA_NOTICE, KEY_REJECTED_NOTICE

SECRET_DIR_SKIP = {".git", "node_modules", ".next", "__pycache__", ".venv", "dist", "artifacts", "docs"}
ROOT = Path(__file__).resolve().parents[1]


def _response(status: int, payload: dict, url: str) -> httpx.Response:
    request = httpx.Request("POST", url)
    return httpx.Response(status, json=payload, request=request)


def _tool(body: dict) -> dict:
    return {"content": [{"type": "tool_use", "name": "record_triage", "input": body}]}


def _files_with(secret: str, root: Path) -> list[str]:
    hits = []
    needle = secret.encode()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in SECRET_DIR_SKIP]
        for name in filenames:
            path = Path(dirpath) / name
            try:
                blob = path.read_bytes()
            except OSError:
                continue
            if needle in blob:
                hits.append(str(path))
    return hits


def test_a_visitor_key_never_persists(client, monkeypatch, caplog, tmp_path):
    secret = "sk-ant-visitor-" + uuid.uuid4().hex
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_RETRY_BACKOFF", "0")
    jane = next(item for item in client.get("/api/triage").json()["items"] if item["email_id"] == "m01")
    outbound: list[dict] = []

    def rejected(url, headers=None, json=None, timeout=None):
        outbound.append({"url": url, "headers": dict(headers or {})})
        return _response(401, {"error": {"message": secret}}, url)

    monkeypatch.setattr(httpx, "post", rejected)
    with caplog.at_level(logging.DEBUG):
        denied = client.post(f"/api/triage/{jane['id']}/live", headers={"X-Lane-Key": secret})
    assert denied.status_code == 200
    assert denied.json()["mode"] == "demo"
    assert denied.json()["notice"] == KEY_REJECTED_NOTICE
    assert secret not in denied.text
    assert denied.json()["triage"]["model"] == "rules"
    assert outbound[-1]["headers"]["x-api-key"] == secret

    echoed = {
        "category": "lead",
        "confidence": 0.8,
        "name": "Jane Cole",
        "company": "Acme Robotics",
        "budget": "$8,000",
        "intent": "hire an automation freelancer",
        "draft_reply": f"Hi Jane, ignore {secret}",
    }

    def accepted(url, headers=None, json=None, timeout=None):
        outbound.append({"url": url, "headers": dict(headers or {})})
        return _response(200, _tool(echoed), url)

    monkeypatch.setattr(httpx, "post", accepted)
    with caplog.at_level(logging.DEBUG):
        lived = client.post(
            f"/api/triage/{jane['id']}/live",
            headers={"X-Lane-Key": secret, "X-Lane-Provider": "anthropic"},
        )
    assert lived.status_code == 200
    body = lived.json()
    assert body["mode"] == "anthropic"
    assert body["notice"] is None
    assert secret not in lived.text
    assert "[redacted]" in body["triage"]["draft_reply"]
    assert body["triage"]["model"] == "anthropic"

    def quota(url, headers=None, json=None, timeout=None):
        outbound.append({"url": url, "headers": dict(headers or {})})
        return _response(429, {"error": {"message": secret}}, url)

    monkeypatch.setattr(httpx, "post", quota)
    listed = client.get("/api/triage?limit=200").json()["items"]
    other = next(item for item in listed if item["id"] != jane["id"] and not item["approved"])
    with caplog.at_level(logging.DEBUG):
        limited = client.post(f"/api/triage/{other['id']}/live", headers={"X-Lane-Key": secret})
    assert limited.status_code == 200
    assert limited.json()["notice"] == KEY_QUOTA_NOTICE
    assert secret not in limited.text

    calls_after = {"n": 0}

    def should_not_see_the_key(url, headers=None, json=None, timeout=None):
        calls_after["n"] += 1
        blob = repr(headers) + repr(json)
        assert secret not in blob
        return _response(200, _tool(echoed), url)

    monkeypatch.setattr(httpx, "post", should_not_see_the_key)
    plain = client.post(
        "/api/classify",
        json={
            "from_name": "Jane Cole",
            "from_email": "jane.cole@acmerobotics.com",
            "subject": "Retainer",
            "body": "We are looking for a freelancer. Budget is $8,000.\n\nThanks,\nJane Cole\n",
        },
    )
    assert plain.status_code == 200
    assert plain.json()["model"] == "rules"
    assert calls_after["n"] == 0
    assert os.environ.get("ANTHROPIC_API_KEY", "") != secret
    assert os.environ.get("OPENAI_API_KEY", "") != secret
    assert secret not in caplog.text
    database = b"".join(path.read_bytes() for path in tmp_path.iterdir() if path.is_file())
    assert secret.encode() not in database
    leaked = _files_with(secret, ROOT)
    assert leaked == []
    leaked_tmp = _files_with(secret, tmp_path)
    assert leaked_tmp == []
    desk = (ROOT / "dashboard/src/components/session-key.tsx").read_text()
    assert "localStorage" not in desk
    assert "sessionStorage" not in desk


def test_demo_mode_answers_an_empty_question_without_inventing_one(client):
    response = client.post("/api/classify", json={"subject": "", "body": ""})
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "rules"
    assert body["mode"] == "demo"
    assert "add a key" in body["draft_reply"].lower()
    assert "claude" not in body["draft_reply"].lower()
    assert "gpt" not in body["draft_reply"].lower()
