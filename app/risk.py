"""Structural phishing checks. These look at domains, links, and who the text is for.

A brand name, a bank field, or a sentence aimed at an assistant is a shape, not a
phrase copied from one mailbox. Mentioning an IBAN inside a real project, or
correcting an earlier figure, is not one of those shapes.
"""

from __future__ import annotations

import os
import re

_BRANDS: dict[str, tuple[str, ...]] = {
    "microsoft": ("microsoft.com", "office.com", "office365.com", "live.com", "outlook.com"),
    "docusign": ("docusign.com", "docusign.net"),
    "paypal": ("paypal.com",),
    "google": ("google.com", "gmail.com", "googlemail.com"),
    "apple": ("apple.com", "icloud.com"),
    "stripe": ("stripe.com",),
    "adobe": ("adobe.com",),
    "mcafee": ("mcafee.com",),
    "dhl": ("dhl.com", "dhl.de"),
    "fedex": ("fedex.com",),
    "ups": ("ups.com",),
    "amazon": ("amazon.com", "amazon.co.uk"),
}

_FREE_MAIL = {
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "yahoo.com",
    "icloud.com",
    "aol.com",
    "proton.me",
    "protonmail.com",
}

_LEET = str.maketrans({"0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t"})

_GIFT = re.compile(r"\bgift cards?\b", re.IGNORECASE)
_GIFT_ACT = re.compile(r"\b(codes?|scratch|photo|photograph|buy|pick up)\b", re.IGNORECASE)
_PAYMENT_CHANGE = re.compile(
    r"\b("
    r"(?:remittance|bank|payment|billing) details(?:\s+have\s+been)?\s+updated"
    r"|changed banks"
    r"|switched to a different bank"
    r"|new bank details"
    r"|direct deposit"
    r")\b",
    re.IGNORECASE,
)
_BANK_FIELD = re.compile(
    r"\b(sort code|routing number|account number|iban\s*:|new account)\b",
    re.IGNORECASE,
)
_CREDENTIAL = re.compile(
    r"\b(sign in|log in|login|re-enter your login|enter your (?:email )?password|"
    r"log in with your email password|scan the (?:attached )?qr(?: code)?)\b",
    re.IGNORECASE,
)
_CREDENTIAL_DENIAL = re.compile(r"(?:can't|cannot|unable to)\s+$", re.IGNORECASE)
_ASSISTANT = re.compile(
    r"(ignore (?:all )?previous instructions|classify this email as|you are now|"
    r"auto-send|update the crm|set (?:my |the )?budget)",
    re.IGNORECASE,
)
_ADDRESSED = re.compile(
    r"\b(assistant|ai assistant|language model)\b.{0,160}\b(crm|budget|qualified|classify|ignore|category)\b",
    re.IGNORECASE | re.DOTALL,
)
_SUPPRESSION = re.compile(
    r"(this message is spam|do not alert|don't alert anyone)",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://([^/\s\"'>]+)", re.IGNORECASE)
_ANCHOR = re.compile(
    r"<a\b[^>]*href=[\"']https?://([^\"'/]+)[^\"']*[\"'][^>]*>(.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_DOMAIN_IN_TEXT = re.compile(r"\b([a-z0-9-]+(?:\.[a-z0-9-]+)+)\b", re.IGNORECASE)
_COMMENT = re.compile(r"<!--(.*?)-->", re.DOTALL)


def _domain(address: str) -> str:
    if "@" not in (address or ""):
        return ""
    return address.rsplit("@", 1)[1].lower().strip().rstrip(">")


def _legit(domain: str, suffixes: tuple[str, ...]) -> bool:
    return any(domain == suffix or domain.endswith("." + suffix) for suffix in suffixes)


def _host(value: str) -> str:
    return value.lower().split(":")[0].strip(".")


def lookalike_domain(address: str) -> bool:
    domain = _domain(address)
    if not domain:
        return False
    labels = re.split(r"[.\-]", domain)
    for label in labels:
        folded = label.translate(_LEET)
        for brand, suffixes in _BRANDS.items():
            if brand in folded and not _legit(domain, suffixes):
                return True
    return False


def display_name_mismatch(email: dict, known_contacts: list[dict] | None) -> bool:
    name = (email.get("from_name") or "").strip().casefold()
    domain = _domain(email.get("from_email") or "")
    if not name or not domain or not known_contacts:
        return False
    for contact in known_contacts:
        contact_name = (contact.get("name") or "").strip().casefold()
        contact_domain = _domain(contact.get("email") or "")
        if contact_name and contact_name == name and contact_domain and contact_domain != domain:
            return True
    return False


def brand_impersonation(email: dict) -> bool:
    """The display name is a known company and the domain is not that company's."""
    name = email.get("from_name") or ""
    domain = _domain(email.get("from_email") or "")
    if not name or not domain:
        return False
    for brand, suffixes in _BRANDS.items():
        if re.search(rf"\b{brand}\b", name, re.IGNORECASE) and not _legit(domain, suffixes):
            return True
    return False


def mismatched_link(raw: str) -> bool:
    """Visible link text names a domain the href does not use."""
    for host, text in _ANCHOR.findall(raw or ""):
        target = _host(host)
        for mentioned in _DOMAIN_IN_TEXT.findall(re.sub(r"<[^>]+>", " ", text)):
            shown = _host(mentioned)
            if shown != target and not target.endswith("." + shown) and not shown.endswith("." + target):
                return True
    return False


def _credential_ask(text: str) -> bool:
    for match in _CREDENTIAL.finditer(text or ""):
        window = text[max(0, match.start() - 16) : match.start()]
        if _CREDENTIAL_DENIAL.search(window):
            continue
        return True
    return False


def _external_url(text: str, sender: str) -> bool:
    sender_domain = _domain(sender)
    for host in _URL.findall(text or ""):
        target = _host(host)
        if not sender_domain:
            return True
        if target == sender_domain or target.endswith("." + sender_domain):
            continue
        return True
    return False


def _payment_change(text: str) -> bool:
    if _PAYMENT_CHANGE.search(text or "") and (
        _BANK_FIELD.search(text or "") or re.search(r"\b(payment|paycheck|deposit|account)\b", text or "", re.I)
    ):
        return True
    if re.search(r"\bsort code\s*:", text or "", re.I) and re.search(r"\baccount\s*:", text or "", re.I):
        return True
    if re.search(r"\brouting\b", text or "", re.I) and re.search(r"\baccount\b", text or "", re.I):
        if re.search(r"\b(update|new|switch|deposit|paycheck)\b", text or "", re.I):
            return True
    return False


def _owner_impersonation(email: dict, text: str) -> bool:
    owner = os.environ.get("OWNER_NAME", "Asad Rehman").strip().casefold()
    name = (email.get("from_name") or "").strip().casefold()
    domain = _domain(email.get("from_email") or "")
    if not owner or name != owner or domain not in _FREE_MAIL:
        return False
    return bool(_GIFT.search(text) or _payment_change(text) or re.search(r"keep this between us", text, re.I))


def _hidden_text(raw: str) -> str:
    return "\n".join(_COMMENT.findall(raw or ""))


def _assistant_instruction(text: str) -> bool:
    if _ASSISTANT.search(text or ""):
        return True
    return bool(_ADDRESSED.search(text or ""))


def assess_risk(email: dict, text: str, raw: str = "", known_contacts: list[dict] | None = None) -> list[str]:
    """Return risk flags. A suppression note is recorded and does not force the category."""
    flags: list[str] = []
    body = raw or email.get("body") or ""
    hidden = _hidden_text(body)
    combined = f"{text}\n{hidden}"
    sender = email.get("from_email") or ""
    if lookalike_domain(sender):
        flags.append("lookalike_domain")
    if display_name_mismatch(email, known_contacts):
        flags.append("display_name_mismatch")
    if brand_impersonation(email):
        flags.append("brand_impersonation")
    if mismatched_link(body):
        flags.append("mismatched_link")
    if _payment_change(combined):
        flags.append("payment_change")
    if _GIFT.search(combined) and _GIFT_ACT.search(combined):
        flags.append("gift_card")
    if _owner_impersonation(email, combined):
        flags.append("owner_impersonation")
    credential = _credential_ask(combined)
    if credential and (_external_url(combined, sender) or re.search(r"\bqr\b", combined, re.I)):
        flags.append("credential_request")
    if _assistant_instruction(combined):
        flags.append("prompt_injection")
    elif _SUPPRESSION.search(combined):
        flags.append("instruction_suppression")
    return flags


def hard_flags(flags: list[str]) -> list[str]:
    """Flags that block a normal reply and a CRM write.

    A note that only says "do not alert" is recorded and ignored, so a real
    outage cannot hide behind it.
    """
    return [flag for flag in flags if flag != "instruction_suppression"]
