"""Turn a raw message into the text the rules and the model both see."""

from __future__ import annotations

import re

from app.normalize import open_channels

_FORWARD = re.compile(
    r"(?:-{5,}\s*Forwarded message\s*-{5,}|-----Original Message-----)",
    re.IGNORECASE,
)
_FROM = re.compile(r"^From:\s*(?P<who>.+)$", re.IGNORECASE | re.MULTILINE)
_INJECTION_NOTE = re.compile(
    r"\((?:note to (?:any )?ai assistant|system note)[^)]{0,400}\)",
    re.IGNORECASE,
)
_WROTE = re.compile(r"^On .+ wrote:\s*$", re.IGNORECASE)
_QUOTE_SPLIT = re.compile(r"\nOn .{0,180} wrote:\s*\n", re.IGNORECASE)


def html_to_text(value: str) -> str:
    """Visible text only. Hidden, off-screen, white, and tiny type are not included."""
    return open_channels(value or "").visible


def hidden_text(value: str) -> str:
    """Text recovered from hiding or from an encoded channel, not the visible reading."""
    return open_channels(value or "").concealed


def unwrap_forward(email: dict) -> dict:
    """Use the inner sender when the message is a forward. Keep the outer address."""
    body = email.get("body") or ""
    match = _FORWARD.search(body)
    if not match:
        return email
    inner = body[match.end() :]
    found = _FROM.search(inner)
    if not found:
        return email
    who = found.group("who").strip()
    name, address = _split_from(who)
    prepared = dict(email)
    prepared["forwarded_by"] = email.get("from_email") or ""
    prepared["body"] = inner
    if address:
        prepared["from_email"] = address
    if name:
        prepared["from_name"] = name
    return prepared


def _split_from(value: str) -> tuple[str, str]:
    bracket = re.match(r"\s*(?P<name>.*?)\s*<(?P<email>[^>]+)>", value)
    if bracket:
        return bracket.group("name").strip().strip('"'), bracket.group("email").strip()
    if "@" in value:
        return "", value.strip()
    return value.strip(), ""


def strip_injection_notes(text: str) -> str:
    return _INJECTION_NOTE.sub(" ", text)


def strip_quotes(text: str) -> str:
    """Drop quoted reply history so an older pitch cannot score the new message."""
    kept: list[str] = []
    for line in (text or "").splitlines():
        if line.lstrip().startswith(">"):
            continue
        if _WROTE.match(line.strip()):
            break
        kept.append(line)
    joined = "\n".join(kept)
    match = _QUOTE_SPLIT.search("\n" + joined)
    if match:
        joined = ("\n" + joined)[: match.start()]
    return joined.strip()


def head_and_tail(text: str, limit: int = 20_000) -> str:
    if len(text) <= limit:
        return text
    head = limit * 3 // 5
    tail = limit - head
    return text[:head] + "\n\n[truncated]\n\n" + text[-tail:]
