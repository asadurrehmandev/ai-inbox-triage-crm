"""Turn a raw message into the text the rules and the model both see."""

from __future__ import annotations

import re
from html.parser import HTMLParser

_FORWARD = re.compile(
    r"(?:-{5,}\s*Forwarded message\s*-{5,}|-----Original Message-----)",
    re.IGNORECASE,
)
_FROM = re.compile(r"^From:\s*(?P<who>.+)$", re.IGNORECASE | re.MULTILINE)
_INJECTION_NOTE = re.compile(
    r"\((?:note to (?:any )?ai assistant|system note)[^)]{0,240}\)",
    re.IGNORECASE,
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in {"br", "p", "div", "tr", "li"}:
            self.parts.append("\n")


def html_to_text(value: str) -> str:
    if not value or "<" not in value or ">" not in value:
        return value or ""
    parser = _TextExtractor()
    parser.feed(value)
    parser.close()
    text = "".join(parser.parts)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


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


def head_and_tail(text: str, limit: int = 20_000) -> str:
    if len(text) <= limit:
        return text
    head = limit * 3 // 5
    tail = limit - head
    return text[:head] + "\n\n[truncated]\n\n" + text[-tail:]
