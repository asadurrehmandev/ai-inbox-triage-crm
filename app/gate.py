"""The only CRM filing decision. Accept and Claude auto-file both use it.

Stored flags and the model's category are not enough. The message is read
again. A suspicious row cannot become a lead. Money movement, including a
store card, a claim code, or a change of where invoices are sent, is refused.
A sender is authenticated only from a trusted receiving server, or from a
DKIM signature checked on the raw message. With no trusted authserv-id, every
sender is a first contact. A subject of "Re:" is not a thread. A first contact
that carries a risk feature needs a second confirm, and that confirm is logged.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.dkim_verify import verified_dkim_domains

from app.classifier import known_sender
from app.normalize import open_channels
from app.prepare import strip_quotes
from app.risk import assess_risk, deceptive_pay_link, hard_flags, invoice_address_notice, payment_related

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
_VOICEMAIL = re.compile(
    r"\bvoice[\s-]?mails?\b|\bvoice[\s-]?messages?\b|\bvoice[\s-]?msgs?\b",
    re.IGNORECASE,
)
_ATTACHMENT_HEADER = re.compile(r"content-disposition:\s*attachment", re.IGNORECASE)
_QR_WORD = re.compile(r"\bqr(?:\s*-?\s*codes?)?\b", re.IGNORECASE)
_MEETING_STARTING = re.compile(
    r"\bmeetings?\b(?:\s+\w+){0,4}\s+start(?:ing|s)\b",
    re.IGNORECASE,
)
_QUOTA = re.compile(
    r"\b(?:mail\s*box|inbox|storage)\b.{0,40}\b(?:quota|full|limit)\b"
    r"|\bquota\b.{0,30}\b(?:exceeded|reached|full|warning)\b"
    r"|\bstorage\s+(?:quota|is\s+full|full|limit)\b",
    re.IGNORECASE | re.DOTALL,
)
_LOGIN_PATH = re.compile(r"(?:login|log-in|signin|sign-in|sign_in|/sso\b|password)", re.IGNORECASE)
_FORM = re.compile(r"<\s*form\b", re.IGNORECASE)
_CHECKOUT_WORD = re.compile(r"\bcheckout\b", re.IGNORECASE)
_ADDENDUM = re.compile(
    r"\bpayment\s+addend(?:um|a)\b"
    r"|\baddend(?:um|a)\b.{0,40}\bpayments?\b"
    r"|\bpayment\s+instructions\b",
    re.IGNORECASE | re.DOTALL,
)
_CHANGED_TERMS = re.compile(
    r"\b(?:updated|revised|changed|new)\s+terms\b"
    r"|\bterms\b.{0,30}\b(?:changed|updated|revised)\b",
    re.IGNORECASE | re.DOTALL,
)
_CC_AP = re.compile(
    r"\bcc\b.{0,50}\b(?:ap@|ap\b|a/p\b|accounts\s+payable)\b",
    re.IGNORECASE | re.DOTALL,
)
_DOCUMENT = re.compile(r"\b(?:receipts?|invoices?|paid\s+inv|inv\s*#\s*\d+)\b", re.IGNORECASE)
_DKIM_PASS = re.compile(r"\bdkim\s*=\s*pass\b([^;]*)", re.IGNORECASE)
_HEADER_D = re.compile(r"\bheader\.d\s*=\s*([^\s;]+)", re.IGNORECASE)
_HEADER_I = re.compile(r"\bheader\.i\s*=\s*([^\s;]+)", re.IGNORECASE)
_SPF = re.compile(r"\bspf\s*=\s*(pass|fail|softfail|neutral|none)\b", re.IGNORECASE)
_DMARC = re.compile(r"\bdmarc\s*=\s*(pass|fail|none)\b", re.IGNORECASE)
_MSG_ID = re.compile(r"<([^<>\s]+)>")
_ZW = re.compile("[\u180e\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")
# authserv-id, then an optional integer version, then the semicolon.
# A comment or a zero-width character means the header is not trusted.
_AUTHSERV_FIELD = re.compile(
    r"^([A-Za-z0-9._-]+)(?:\s+\d+)?\s*;",
    re.IGNORECASE,
)
_ARC_INSTANCE = re.compile(r"^i\s*=\s*\d+\s*;\s*", re.IGNORECASE)


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


def _domain_of(token: str) -> str:
    token = token.strip().strip("<>").strip(".").lower()
    if "@" in token:
        token = token.rsplit("@", 1)[1]
    return token.removeprefix("www.").strip(".")


def _aligned(signing: str, sender: str) -> bool:
    signing = _domain_of(signing)
    sender = _domain_of(sender)
    if not signing or not sender or "@" in signing:
        return False
    return signing == sender or sender.endswith("." + signing) or signing.endswith("." + sender)


def _header_pairs(email: dict) -> list[tuple[str, str]]:
    raw = email.get("headers") or {}
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raw = {}
        else:
            try:
                raw = json.loads(text)
            except json.JSONDecodeError:
                raw = {}
    pairs: list[tuple[str, str]] = []
    if isinstance(raw, dict):
        for key, value in raw.items():
            values = value if isinstance(value, list) else [value]
            for item in values:
                pairs.append((str(key).lower(), str(item)))
    for key in ("authentication_results", "auth_results"):
        if email.get(key):
            pairs.append(("authentication-results", str(email[key])))
    return pairs


def trusted_authserv_ids() -> set[str]:
    """Exact authserv-ids of the receiving mail provider. Empty trusts nobody."""
    raw = os.environ.get("TRUSTED_AUTHSERV_ID", "")
    return {part.strip().lower().strip(".") for part in raw.split(",") if part.strip()}


def _authserv_id(blob: str) -> str:
    """The authserv-id, or empty when the field is not a plain token.

    Zero-width characters and comments are rejected. The id is not taken as
    a prefix of a longer token.
    """
    text = (blob or "").strip()
    text = _ARC_INSTANCE.sub("", text, count=1)
    field = text.split(";", 1)[0]
    if _ZW.search(field) or "(" in field or ")" in field:
        return ""
    match = _AUTHSERV_FIELD.match(text)
    if match is None:
        return ""
    return match.group(1).lower().strip(".")


def _auth_blobs(email: dict) -> list[str]:
    """Authentication-Results first, then ARC, whatever the JSON key order.

    Authentication-Results-Original is a forwarder copy and is not included.
    Within each header, list order is topmost first.
    """
    pairs = _header_pairs(email)
    primary = [value for name, value in pairs if name == "authentication-results"]
    arc = [value for name, value in pairs if name == "arc-authentication-results"]
    return primary + arc


def trusted_auth_blob(email: dict) -> str:
    """The topmost Authentication-Results whose authserv-id is configured.

    Later copies are ignored, including a second header that repeats the
    trusted id. A lookalike such as mx.lane.test.attacker.com does not match
    mx.lane.test. With TRUSTED_AUTHSERV_ID unset, this is empty.
    """
    allowed = trusted_authserv_ids()
    if not allowed:
        return ""
    for blob in _auth_blobs(email):
        if _authserv_id(blob) in allowed:
            return blob
    return ""


def _stored_dkim(email: dict) -> str:
    value = email.get("dkim_verified")
    if value is None:
        return ""
    return str(value).strip().lower()


def authentication(email: dict) -> dict:
    """DKIM, SPF, and DMARC from the one trusted auth result. Only aligned DKIM counts."""
    blob = trusted_auth_blob(email)
    spf_blobs = [blob] if blob else []
    if blob:
        spf_blobs.extend(value for name, value in _header_pairs(email) if name == "received-spf")
    spf_text = "\n".join(spf_blobs)
    dkim = "pass" if blob and _DKIM_PASS.search(blob) else "none"
    spf = _SPF.search(spf_text) if spf_text else None
    if spf is None:
        spf_value = "none"
        for value in spf_blobs[1:]:
            leading = re.match(r"\s*(pass|fail|softfail|neutral|none)\b", value, re.IGNORECASE)
            if leading:
                spf_value = leading.group(1).lower()
                break
    else:
        spf_value = spf.group(1).lower()
    dmarc = _DMARC.search(blob) if blob else None
    return {
        "dkim": dkim,
        "spf": spf_value,
        "dmarc": dmarc.group(1).lower() if dmarc else "none",
        "aligned": sender_authenticated(email),
    }


def dkim_domains(email: dict) -> list[str]:
    """Signing domains from the single trusted auth result, and no other header."""
    blob = trusted_auth_blob(email)
    found: list[str] = []
    if not blob:
        return found
    for match in _DKIM_PASS.finditer(blob):
        rest = match.group(1) or ""
        domain = _HEADER_D.search(rest) or _HEADER_I.search(rest)
        if domain is None:
            continue
        host = _domain_of(domain.group(1))
        if host and host not in found:
            found.append(host)
    return found


def _sender_domain(email: dict) -> str:
    address = email.get("from_email") or ""
    if "@" not in address:
        return ""
    return _domain_of(address.rsplit("@", 1)[1])


def _raw_message(email: dict) -> bytes:
    raw = email.get("raw_message")
    if isinstance(raw, bytes) and raw:
        return raw
    if isinstance(raw, str) and raw:
        return raw.encode()
    return b""


def _domains_align(domains: list[str], sender: str) -> bool:
    return any(_aligned(domain, sender) for domain in domains)


def sender_authenticated(email: dict) -> bool:
    """Aligned DKIM from a checked signature, or from the trusted authserv-id.

    A raw message is checked with dkimpy when that library is installed. A
    failed check is stored as dkim_verified=none and the sender's
    Authentication-Results header is then ignored. A webhook has no raw
    message, so it can only authenticate through TRUSTED_AUTHSERV_ID, which
    is empty by default.
    """
    sender = _sender_domain(email)
    if not sender:
        return False
    stored = _stored_dkim(email)
    if stored == "none":
        return False
    if stored:
        return _domains_align([part.strip() for part in stored.split(",") if part.strip()], sender)
    raw = _raw_message(email)
    if raw:
        checked = verified_dkim_domains(raw)
        if checked is not None:
            return _domains_align(checked, sender)
    return _domains_align(dkim_domains(email), sender)


def _message_ids(value: str) -> list[str]:
    found: list[str] = []
    for token in _MSG_ID.findall(value or ""):
        token = token.strip()
        if token and token not in found:
            found.append(token)
    return found


def referenced_ids(email: dict) -> list[str]:
    chunks = [
        str(email.get("in_reply_to") or ""),
        str(email.get("references") or ""),
        str(email.get("references_header") or ""),
    ]
    for name, value in _header_pairs(email):
        if name in {"in-reply-to", "references"}:
            chunks.append(value)
    found: list[str] = []
    for chunk in chunks:
        for token in _message_ids(chunk):
            if token not in found:
                found.append(token)
    return found


def trusted_thread(email: dict) -> bool:
    """A thread Lane has stored, from a prior participant, with aligned DKIM.

    A subject that starts with Re: is not enough. In-Reply-To or References
    has to name a Message-ID this mailbox already kept.
    """
    if not sender_authenticated(email):
        return False
    ids = referenced_ids(email)
    if not ids:
        return False
    from app import db

    participants = db.thread_participants(ids, exclude_id=str(email.get("id") or ""))
    sender = (email.get("from_email") or "").strip().lower()
    return bool(sender) and sender in participants


def gate_first_contact(email: dict, known_contacts: list[dict] | None) -> bool:
    """Unauthenticated mail is a first contact, even when the CRM knows the address."""
    if not sender_authenticated(email):
        return True
    if trusted_thread(email) or known_sender(email, known_contacts):
        return False
    return True


def is_receipt_or_invoice(email: dict) -> bool:
    """A receipt or an invoice is never auto-filed, whatever the model called it."""
    return bool(_DOCUMENT.search(_readable(email)))


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


def _qr(raw: str) -> bool:
    if _QR_WORD.search(raw):
        return True
    for image in _IMG.finditer(raw):
        blob = image.group(1) or ""
        src = _SRC.search(blob)
        alt = re.search(r"\balt\s*=\s*[\"']([^\"']+)[\"']", blob, re.IGNORECASE)
        haystack = " ".join(
            part for part in (src.group(1) if src else "", alt.group(1) if alt else "") if part
        )
        if _QR_WORD.search(haystack):
            return True
    return False


def _login_or_form(raw: str) -> bool:
    if _FORM.search(raw):
        return True
    for match in _URL.finditer(raw):
        parsed = urlparse(match.group(0).strip().rstrip(").,>"))
        target = f"{parsed.path or ''}?{parsed.query or ''}"
        if _LOGIN_PATH.search(target):
            return True
    return False


def _checkout(raw: str) -> bool:
    urls = list(_URL.finditer(raw))
    if any(_CHECKOUT_WORD.search(match.group(0)) for match in urls):
        return True
    return bool(urls) and bool(_CHECKOUT_WORD.search(raw))


def risk_features(email: dict, known_contacts: list[dict] | None = None) -> list[str]:
    """Structural features that make a first contact unsafe to file in one click.

    A link or image on the From domain counts only when DKIM did not pass for
    that domain. A cid: part with no QR in the name does not count. There is
    no image reader.
    """
    raw = f"{email.get('subject') or ''}\n{email.get('body') or ''}"
    readable = _readable(email)
    sender = _sender_domain(email)
    authed = sender_authenticated(email)
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
        elif not authed:
            reasons.append("link on an unauthenticated domain")
    for image in _IMG.finditer(raw):
        src = _SRC.search(image.group(1) or "")
        if src is None:
            continue
        value = src.group(1).strip()
        lowered = value.lower()
        if lowered.startswith("data:"):
            reasons.append("inline image")
            continue
        if lowered.startswith("cid:"):
            continue
        if lowered.startswith("http"):
            host = _host(value)
            if not _same_org(host, sender):
                reasons.append("image on an unknown domain")
            elif not authed:
                reasons.append("image on an unauthenticated domain")
    if _CALENDAR.search(raw):
        reasons.append("calendar invite")
    if _ATTACHMENT_HEADER.search(raw) or _FILE.search(readable):
        reasons.append("attachment")
    flags = assess_risk(email, readable, email.get("body") or "", known_contacts)
    if {"lookalike_domain", "brand_impersonation", "display_name_mismatch", "mismatched_link"} & set(flags):
        reasons.append("brand and domain do not match")
    return _dedupe(reasons)


def always_confirm_features(email: dict) -> list[str]:
    """Features that need a second confirm even for an authenticated sender."""
    raw = f"{email.get('subject') or ''}\n{email.get('body') or ''}"
    readable = _readable(email)
    reasons: list[str] = []
    if _qr(raw):
        reasons.append("QR code")
    if _MEETING_STARTING.search(readable):
        reasons.append("meeting starting")
    if _VOICEMAIL.search(readable):
        reasons.append("voicemail notice")
    if _QUOTA.search(readable):
        reasons.append("quota or storage notice")
    if _login_or_form(raw):
        reasons.append("login or form link")
    if _checkout(raw):
        reasons.append("checkout link")
    if _ADDENDUM.search(readable):
        reasons.append("payment addendum")
    if _CHANGED_TERMS.search(readable):
        reasons.append("changed terms")
    if _CC_AP.search(readable) and not payment_related(readable):
        reasons.append("also copy accounts payable")
    if invoice_address_notice(readable) and not payment_related(readable):
        reasons.append("where invoices are sent")
    return _dedupe(reasons)


def evaluate_filing(
    email: dict,
    *,
    current_category: str | None,
    target: str,
    known_contacts: list[dict] | None = None,
    link_contacts: list[dict] | None = None,
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
    if deceptive_pay_link(f"{readable}\n{email.get('body') or ''}", email.get("from_email") or "", link_contacts or known_contacts):
        if "deceptive_link" not in flags:
            flags = [*flags, "deceptive_link"]
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
    features: list[str] = []
    if gate_first_contact(email, known_contacts):
        features.extend(risk_features(email, known_contacts))
    features.extend(always_confirm_features(email))
    features = _dedupe(features)
    if features:
        if confirmed:
            return FilingDecision(allow=True, code="confirmed", reasons=features)
        return FilingDecision(
            allow=False,
            needs_confirm=True,
            code="confirm",
            message="Needs a second confirm before this message can be filed",
            reasons=features,
        )
    return FilingDecision(allow=True)


def log_confirmed_filing(email_id: str, reasons: list[str]) -> None:
    """A second confirm is an explicit human override. Keep it in the log."""
    from app import db

    db.insert_filing_log(email_id, "confirmed", reasons)
    log.info("filing_confirmed email_id=%s reasons=%s", email_id, "; ".join(reasons))
