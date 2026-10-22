"""The only CRM filing decision. Accept and Claude auto-file both use it.

Stored flags and the model's category are not enough. The message is read
again. A suspicious row cannot become a lead. Money movement, including a
store card or a claim code, is refused. A first contact that carries a risk
feature needs a second confirm, and that confirm is logged.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.classifier import existing_thread, known_sender
from app.normalize import open_channels
from app.prepare import strip_quotes
from app.risk import assess_risk, hard_flags, payment_related

log = logging.getLogger("lane.gate")

_SHORTENERS = {
    "bit.ly",
    "tinyurl.com",
    "t.co",
    "goo.gl",
    "ow.ly",
    "is.gd",
    "buff.ly",
    "cutt.ly",
    "rb.gy",
    "shorturl.at",
    "tiny.cc",
    "rebrand.ly",
    "t.ly",
}
_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_IMG = re.compile(r"<img\b([^>]*)>", re.IGNORECASE)
_SRC = re.compile(r"\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
_FILE = re.compile(
    r"\b[\w.-]+\.(?:pdf|docx?|xlsx?|pptx?|ics|html?|zip|png|jpe?g)\b",
    re.IGNORECASE,
)
_CALENDAR = re.compile(r"BEGIN:VCALENDAR|text/calendar|METHOD:REQUEST|\.ics\b", re.IGNORECASE)
_VOICEMAIL = re.compile(r"\bvoice[\s-]?mails?\b", re.IGNORECASE)
_ATTACHMENT_HEADER = re.compile(r"content-disposition:\s*attachment", re.IGNORECASE)


class FilingBlocked(Exception):
    """The lead must not be written. confirm=true does not override this."""

    def __init__(self, code: str, message: str, reasons: list[str]) -> None:
        self.code = code
        self.message = message
        self.reasons = list(reasons)
        super().__init__(message)


class FilingConfirm(FilingBlocked):
    """A first-contact risk feature needs an explicit second confirm."""


@dataclass
class FilingDecision:
    allow: bool
    code: str = "ok"
    message: str = ""
    reasons: list[str] = field(default_factory=list)
    needs_confirm: bool = False

    def raise_if_refused(self) -> None:
        if self.allow:
            return
        if self.needs_confirm:
            raise FilingConfirm(self.code, self.message, self.reasons)
        raise FilingBlocked(self.code, self.message, self.reasons)


def _host(url: str) -> str:
    parsed = urlparse(url.strip().rstrip(").,>"))
    host = (parsed.hostname or "").lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def _same_org(host: str, sender_domain: str) -> bool:
    host = host.lower().strip(".").removeprefix("www.")
    sender = sender_domain.lower().strip(".").removeprefix("www.")
    if not host or not sender:
        return False
    return host == sender or host.endswith("." + sender)


def _readable(email: dict) -> str:
    channels = open_channels(email.get("body") or "")
    visible = strip_quotes(channels.visible)
    return f"{email.get('subject') or ''}\n{visible}\n{channels.concealed}"


def _dedupe(reasons: list[str]) -> list[str]:
    found: list[str] = []
    for reason in reasons:
        if reason and reason not in found:
            found.append(reason)
    return found


def risk_features(email: dict, known_contacts: list[dict] | None = None) -> list[str]:
    """Structural features that make a first contact unsafe to file in one click."""
    raw = f"{email.get('subject') or ''}\n{email.get('body') or ''}"
    readable = _readable(email)
    sender = ""
    address = email.get("from_email") or ""
    if "@" in address:
        sender = address.rsplit("@", 1)[1].lower().strip().rstrip(">")
    reasons: list[str] = []
    if "xn--" in sender:
        reasons.append("punycode host")
    for match in _URL.finditer(raw):
        host = _host(match.group(0))
        if not host:
            continue
        if host in _SHORTENERS:
            reasons.append("shortened link")
        elif "xn--" in host:
            reasons.append("punycode host")
        elif not _same_org(host, sender):
            reasons.append("link to an unknown domain")
    image_off_domain = False
    for image in _IMG.finditer(raw):
        src = _SRC.search(image.group(1) or "")
        if src is None:
            image_off_domain = True
            continue
        value = src.group(1).strip()
        if value.lower().startswith(("cid:", "data:")):
            image_off_domain = True
            continue
        if value.lower().startswith("http"):
            if not _same_org(_host(value), sender):
                image_off_domain = True
        else:
            image_off_domain = True
    if image_off_domain or re.search(r"\bcid:", raw, re.IGNORECASE):
        reasons.append("image or QR on an unknown domain")
    if _CALENDAR.search(raw):
        reasons.append("calendar invite")
    if _ATTACHMENT_HEADER.search(raw) or _FILE.search(readable):
        reasons.append("attachment")
    if _VOICEMAIL.search(readable):
        reasons.append("voicemail notice")
    flags = assess_risk(email, readable, email.get("body") or "", known_contacts)
    if {"lookalike_domain", "brand_impersonation", "display_name_mismatch", "mismatched_link"} & set(flags):
        reasons.append("brand and domain do not match")
    return _dedupe(reasons)


def evaluate_filing(
    email: dict,
    *,
    current_category: str | None,
    target: str,
    known_contacts: list[dict] | None = None,
    confirmed: bool = False,
) -> FilingDecision:
    """Decide whether this message may be written to the CRM as a lead."""
    if target != "lead":
        return FilingDecision(allow=True)
    if (current_category or "").strip().lower() == "suspicious":
        return FilingDecision(
            allow=False,
            code="suspicious",
            message="blocked: a suspicious message cannot be filed as a lead",
            reasons=["category is suspicious"],
        )
    readable = _readable(email)
    flags = assess_risk(email, readable, email.get("body") or "", known_contacts)
    if payment_related(readable):
        return FilingDecision(
            allow=False,
            code="payment",
            message="payment-related: verify by phone",
            reasons=["payment-related: verify by phone"],
        )
    blocking = hard_flags(flags)
    if blocking:
        return FilingDecision(
            allow=False,
            code="security",
            message="blocked: verify by phone or security review",
            reasons=blocking,
        )
    features = risk_features(email, known_contacts)
    first_contact = not known_sender(email, known_contacts) and not existing_thread(email)
    if first_contact and features:
        if confirmed:
            return FilingDecision(allow=True, code="confirmed", reasons=features)
        return FilingDecision(
            allow=False,
            needs_confirm=True,
            code="confirm",
            message="Needs a second confirm before this first-contact message can be filed",
            reasons=features,
        )
    return FilingDecision(allow=True)


def log_confirmed_filing(email_id: str, reasons: list[str]) -> None:
    """A second confirm is an explicit human override. Keep it in the log."""
    from app import db

    db.insert_filing_log(email_id, "confirmed", reasons)
    log.info("filing_confirmed email_id=%s reasons=%s", email_id, "; ".join(reasons))
