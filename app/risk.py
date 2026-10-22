"""Structural phishing checks. These look at domains, links, and who the text is for.

A brand name, a bank field, or a sentence aimed at an assistant is a shape, not a
phrase copied from one mailbox. Mentioning an IBAN inside a real project, or
correcting an earlier figure, is not one of those shapes. Text is folded
(NFKC and confusables) before the checks run, and hidden HTML is included.
"""

from __future__ import annotations

import os
import re

from app.normalize import fold
from app.prepare import hidden_text

_BRANDS: dict[str, tuple[str, ...]] = {
    "microsoft": ("microsoft.com", "office.com", "office365.com", "live.com", "outlook.com"),
    "sharepoint": ("microsoft.com", "office.com", "office365.com", "sharepoint.com"),
    "onedrive": ("microsoft.com", "office.com", "live.com", "sharepoint.com"),
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
_CHANGE = (
    r"(?:updated|update the|update our|please update|changed|no longer valid|"
    r"no longer in use|switched|vendor master|effective immediately)"
)
_RAIL = (
    r"(?:ach|aba|routing(?:\s+number)?|sort code|bank details|"
    r"remittance details|remittance destination|direct deposit|iban|bic|swift)"
)
_RAIL_CHANGE = re.compile(
    rf"\b{_CHANGE}\b.{{0,120}}\b{_RAIL}\b|\b{_RAIL}\b.{{0,120}}\b{_CHANGE}\b",
    re.IGNORECASE | re.DOTALL,
)
_ACCOUNT_NUMBER = re.compile(r"\b\d[\d\s-]{5,}\d\b")
_WIRE_REQUEST = re.compile(
    r"\b(?:please\s+)?(?:wire|transfer)\b"
    r"(?:[^.\n]{0,120})\b(?:account|routing|aba|iban|funds|retainer|deposit|wise)\b",
    re.IGNORECASE,
)
_CREDENTIAL = re.compile(
    r"\b(sign in|log in|login|re-enter your login|enter your (?:email )?password|"
    r"log in with your email password|scan the (?:attached )?qr(?: code)?|"
    r"authenticate|unlock (?:the |your )?account|"
    r"verify (?:your )?(?:mailbox|account|ownership|identity)|"
    r"approve (?:the |this )?(?:push|prompt|sign-in)|"
    r"(?:email )?passcode|portal password|one-time code|6-digit code)\b",
    re.IGNORECASE,
)
_SECRET_REPLY = re.compile(
    r"\b(?:reply|respond|send)\b[^.\n]{0,80}\b(?:password|passcode|one-time code)\b",
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
_MACHINE = re.compile(r"\b[a-z][a-z0-9_]{2,}\s*=\s*[^\s;,]{1,40}", re.IGNORECASE)
_SYSTEM_LINE = re.compile(r"(?m)^\s*system\s*:", re.IGNORECASE)
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
_DANGEROUS_FILE = re.compile(
    r"\.(?:pdf|docx?|xlsx?|pptx?|zip|jpe?g|png|html?)\.(?:exe|scr|js|bat|cmd|vbs|hta|html?)\b"
    r"|\.(?:exe|scr|bat|cmd|vbs|hta)\b"
    r"|\benable (?:content|macros)\b"
    r"|attached[^.\n]{0,40}\.html?\b",
    re.IGNORECASE,
)
_HIDDEN_INSTRUCTION = re.compile(
    r"\b(ignore|disregard|assistant|model|crm|budget|qualified|classify|override)\b",
    re.IGNORECASE,
)


def _domain(address: str) -> str:
    if "@" not in (address or ""):
        return ""
    return address.rsplit("@", 1)[1].lower().strip().rstrip(">")


def _legit(domain: str, suffixes: tuple[str, ...]) -> bool:
    return any(domain == suffix or domain.endswith("." + suffix) for suffix in suffixes)


def _host(value: str) -> str:
    return fold(value).lower().split(":")[0].strip(".")


def free_mail(address: str) -> bool:
    return _domain(address) in _FREE_MAIL


def _edit_distance(left: str, right: str) -> int:
    if abs(len(left) - len(right)) > 2:
        return 3
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, start=1):
        current = [i]
        for j, b in enumerate(right, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def lookalike_domain(address: str) -> bool:
    """An email address or a bare host that imitates a known company."""
    if "@" in (address or ""):
        domain = _domain(address)
    else:
        domain = (address or "").lower().split("/")[0].split(":")[0].strip(".")
    if not domain or "." not in domain:
        return False
    folded = fold(domain)
    labels = re.split(r"[.\-]", folded)
    for label in labels:
        leet = label.translate(_LEET)
        for brand, suffixes in _BRANDS.items():
            if brand not in leet and brand not in label:
                continue
            if not _legit(domain, suffixes):
                return True
            # The raw domain only matches the brand after homoglyph folding.
            if folded != domain and _legit(folded, suffixes):
                return True
    return False


def display_name_mismatch(email: dict, known_contacts: list[dict] | None) -> bool:
    name = fold(email.get("from_name") or "").strip().casefold()
    domain = _domain(email.get("from_email") or "")
    if not name or not domain or not known_contacts:
        return False
    for contact in known_contacts:
        contact_name = fold(contact.get("name") or "").strip().casefold()
        contact_domain = _domain(contact.get("email") or "")
        if contact_name and contact_name == name and contact_domain and contact_domain != domain:
            return True
    return False


def brand_impersonation(email: dict) -> bool:
    """The display name is a known company and the domain is not that company's."""
    name = fold(email.get("from_name") or "")
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


def _urls(text: str) -> list[str]:
    return [_host(host) for host in _URL.findall(text or "")]


def _external_url(text: str, sender: str) -> bool:
    sender_domain = _domain(sender)
    hosts = _urls(text)
    if not hosts:
        return False
    if not sender_domain:
        return True
    return any(target != sender_domain and not target.endswith("." + sender_domain) for target in hosts)


def _brand_lure(text: str, sender: str) -> bool:
    """A known brand in the body, an unlock or sign-in, and a link that is not that brand."""
    if not _credential_ask(text) or not _urls(text):
        return False
    domain = _domain(sender)
    for brand, suffixes in _BRANDS.items():
        if not re.search(rf"\b{brand}\b", text, re.IGNORECASE):
            continue
        if _legit(domain, suffixes):
            continue
        if any(not _legit(host, suffixes) for host in _urls(text)):
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
        if re.search(r"\b(update|new|switch|deposit|paycheck|wire|transfer)\b", text or "", re.I):
            return True
    if _RAIL_CHANGE.search(text or "") and _ACCOUNT_NUMBER.search(text or ""):
        return True
    return False


def _owner_name() -> str:
    return os.environ.get("OWNER_NAME", "Asad Rehman").strip()


def _near_owner(email: dict) -> bool:
    owner = fold(_owner_name()).casefold()
    name = fold(email.get("from_name") or "").strip().casefold()
    if owner and name == owner:
        return True
    local = fold((email.get("from_email") or "").split("@", 1)[0])
    compact_owner = re.sub(r"[^a-z]", "", owner)
    compact_local = re.sub(r"[^a-z]", "", local.casefold())
    if not compact_owner or not compact_local:
        return False
    return _edit_distance(compact_local, compact_owner) <= 1


def _owner_impersonation(email: dict, text: str) -> bool:
    domain = _domain(email.get("from_email") or "")
    if domain not in _FREE_MAIL or not _near_owner(email):
        return False
    return bool(
        _GIFT.search(text)
        or _payment_change(text)
        or _WIRE_REQUEST.search(text)
        or re.search(r"keep this between us", text, re.I)
    )


def _machine_payload(text: str) -> bool:
    if _SYSTEM_LINE.search(text or "") and _MACHINE.search(text or ""):
        return True
    return len(_MACHINE.findall(text or "")) >= 2 and ";" in (text or "")


def _assistant_instruction(text: str) -> bool:
    if _ASSISTANT.search(text or ""):
        return True
    if _ADDRESSED.search(text or ""):
        return True
    return _machine_payload(text or "")


def _credential_request(text: str, sender: str) -> bool:
    if _SECRET_REPLY.search(text or ""):
        return True
    if _DANGEROUS_FILE.search(text or "") and (_credential_ask(text or "") or re.search(r"\bapprove the\b", text or "", re.I)):
        return True
    if _untrusted_challenge(text or "", sender):
        return True
    if not _credential_ask(text or ""):
        return False
    if re.search(r"\bqr\b", text or "", re.I):
        return True
    if not _urls(text or ""):
        return False
    # A secret or an unlock on the sender's own domain still counts.
    secret = re.search(r"\b(passcode|password|one-time code|6-digit code)\b", text or "", re.I)
    if secret or _external_url(text, sender) or _brand_lure(text, sender):
        return True
    return False


def _untrusted_challenge(text: str, sender: str) -> bool:
    """Verify or unlock, plus a link that is not the brand the sender claims to be."""
    if not re.search(
        r"\b(?:verify (?:your )?(?:mailbox|account|ownership|identity)|unlock (?:the |your )?account)\b",
        text,
        re.IGNORECASE,
    ):
        return False
    hosts = _urls(text)
    if not hosts:
        return False
    domain = _domain(sender)
    for suffixes in _BRANDS.values():
        if _legit(domain, suffixes) and all(_legit(host, suffixes) for host in hosts):
            return False
    return True


def assess_risk(email: dict, text: str, raw: str = "", known_contacts: list[dict] | None = None) -> list[str]:
    """Return risk flags. A suppression note is recorded and does not force the category."""
    flags: list[str] = []
    body = raw or email.get("body") or ""
    hidden = fold(hidden_text(body))
    combined = fold(f"{text}\n{hidden}")
    sender = email.get("from_email") or ""
    raw_hosts = [host.lower().split(":")[0] for host in _URL.findall(body)]
    if lookalike_domain(sender) or any(lookalike_domain(host) for host in raw_hosts):
        flags.append("lookalike_domain")
    if display_name_mismatch(email, known_contacts):
        flags.append("display_name_mismatch")
    if brand_impersonation(email) or _brand_lure(combined, sender):
        flags.append("brand_impersonation")
    if mismatched_link(body):
        flags.append("mismatched_link")
    if _payment_change(combined):
        flags.append("payment_change")
    if _GIFT.search(combined) and _GIFT_ACT.search(combined):
        flags.append("gift_card")
    if _owner_impersonation(email, combined):
        flags.append("owner_impersonation")
    if free_mail(sender) and _WIRE_REQUEST.search(combined):
        flags.append("payment_request")
    if _credential_request(combined, sender):
        flags.append("credential_request")
    if _DANGEROUS_FILE.search(combined) or _DANGEROUS_FILE.search(body or ""):
        flags.append("dangerous_attachment")
    if hidden and _HIDDEN_INSTRUCTION.search(hidden):
        flags.append("prompt_injection")
    elif _assistant_instruction(combined):
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


def money_movement(text: str) -> bool:
    """A request to wire funds or to change a payment rail. A receipt is not one."""
    folded = fold(text or "")
    return bool(_payment_change(folded) or _WIRE_REQUEST.search(folded) or _RAIL_CHANGE.search(folded))


def blocks_autofile(email: dict, text: str, flags: list[str], budget: str | None, category: str) -> bool:
    """Money movement and uncertain mail are never written to the CRM on their own.

    A free-mail sender with a price and a request to pay, wire, or change an
    account is blocked. So is any message that changes a wire, ACH, routing
    number, or bank detail, even when a model called it a lead.
    """
    if category in {"spam", "suspicious", "review"}:
        return True
    if hard_flags(flags) or "budget_not_in_body" in flags:
        return True
    folded = fold(text or "")
    if _payment_change(folded) or _WIRE_REQUEST.search(folded) or _RAIL_CHANGE.search(folded):
        return True
    if free_mail(email.get("from_email") or "") and budget and re.search(
        r"\b(wire|transfer|ach|routing|bank details|account number)\b", folded, re.I
    ):
        return True
    return False
