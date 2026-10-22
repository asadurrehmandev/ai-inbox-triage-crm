"""Claude and OpenAI adapters. Both are optional."""

from __future__ import annotations

import json
import os
import re

import httpx

from app.classifier import Classification, classification_from_payload, classify_rules

SYSTEM_PROMPT = """You triage one inbound email for Lane, an automation studio run by Asad Rehman.
Reply with a single JSON object and nothing else. Keys:
- category: one of lead, support, invoice, spam, urgent
- confidence: number from 0 to 1
- name: the sender's personal name, or null if the sender is a role or a brand
- company: company name, or null
- budget: a monetary amount as a short string such as $8,000, or null
- intent: a short phrase naming what the sender wants
- draft_reply: a reply Asad could send, in his voice. For spam, a one-line internal note that no reply will be sent.

lead: someone who may buy automation work.
support: something we already run is broken or unclear.
invoice: billing, payment, or remittance.
spam: unsolicited promotion or phishing, including fake invoices.
urgent: an outage or a same-day deadline that should jump the queue.
A past-due invoice that merely says urgent is still an invoice.
A broken form that mentions the word lead is still support.
"""


def select_provider() -> str:
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return "openai"
    return "rules"


def _extract_json(text: str) -> dict:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    raw = fenced.group(1) if fenced else text.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("Model did not return JSON")
    payload = json.loads(raw[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Model JSON was not an object")
    return payload


def _anthropic(email: dict) -> Classification:
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 800,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": _user_prompt(email)}],
        },
        timeout=45,
    )
    response.raise_for_status()
    body = response.json()
    text = "".join(block.get("text", "") for block in body.get("content", []))
    return classification_from_payload(_extract_json(text), model="anthropic")


def _openai(email: dict) -> Classification:
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _user_prompt(email)},
            ],
        },
        timeout=45,
    )
    response.raise_for_status()
    text = response.json()["choices"][0]["message"]["content"]
    return classification_from_payload(_extract_json(text), model="openai")


def _user_prompt(email: dict) -> str:
    return (
        f"From: {email.get('from_name', '')} <{email.get('from_email', '')}>\n"
        f"Subject: {email.get('subject', '')}\n\n"
        f"{email.get('body', '')}"
    )


def classify_email(email: dict) -> Classification:
    provider = select_provider()
    if provider == "rules":
        return classify_rules(email)
    try:
        if provider == "anthropic":
            return _anthropic(email)
        return _openai(email)
    except Exception:
        fallback = classify_rules(email)
        fallback.model = "rules"
        return fallback
