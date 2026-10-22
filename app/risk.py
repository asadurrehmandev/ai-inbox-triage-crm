"""Phishing, fraud, and prompt-injection checks. These run before category scoring."""

from __future__ import annotations

import re

# Brands and the domains that are allowed to send as that brand.
_BRANDS: dict[str, tuple[str, ...]] = {
    "microsoft": ("microsoft.com", "office.com", "office365.com", "live.com", "outlook.com"),
    "docusign": ("docusign.com", "docusign.net"),
    "paypal": ("paypal.com",),
    "google": ("google.com", "gmail.com"),
    "apple": ("apple.com", "icloud.com"),
    "stripe": ("stripe.com",),
    "adobe": ("adobe.com",),
    "mcafee": ("mcafee.com",),
}

_LEET = str.maketrans({"0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t"})

_BANK = re.compile(
    r"\b(iban|swift|routing number|changed banks|new bank|new account|bank details|wire (the )?(funds|payment))\b",
    re.IGNORECASE,
)
_CREDENTIAL = re.compile(
    r"(verify your [\w\s]{0,40}credentials|log in with your email password|confirm your password|"
    r"enter your (?:email )?password|re-?authenticate your mailbox)",
    re.IGNORECASE,
)
_INJECTION = re.compile(
    r"(ignore (?:all )?previous instructions|system note|classify this|"
    r"auto-send|mark .{0,40} as spam|you are now|disregard (?:the |all )?(?:above|prior))",
    re.IGNORECASE,
)
_SUPPRESSION = re.compile(
    r"(this message is spam|do not alert|don't alert anyone)",
    re.IGNORECASE,
)


def _domain(address: str) -> str:
    if "@" not in (address or ""):
        return ""
    return address.rsplit("@", 1)[1].lower().strip().rstrip(">")


def _legit(domain: str, suffixes: tuple[str, ...]) -> bool:
    return any(domain == suffix or domain.endswith("." + suffix) for suffix in suffixes)


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


def assess_risk(email: dict, text: str, known_contacts: list[dict] | None = None) -> list[str]:
    """Return risk flags. Suppression attempts are recorded but do not force the category."""
    flags: list[str] = []
    if lookalike_domain(email.get("from_email") or ""):
        flags.append("lookalike_domain")
    if display_name_mismatch(email, known_contacts):
        flags.append("display_name_mismatch")
    if _BANK.search(text):
        flags.append("bank_change")
    if _CREDENTIAL.search(text):
        flags.append("credential_request")
    if _INJECTION.search(text):
        flags.append("prompt_injection")
    if _SUPPRESSION.search(text) and "prompt_injection" not in flags:
        flags.append("instruction_suppression")
    return flags


def hard_flags(flags: list[str]) -> list[str]:
    """Flags that block categorization, the CRM, and a normal reply.

    A note that only says "do not alert" is recorded and ignored. Obeying it
    would let a sender hide a real outage.
    """
    return [flag for flag in flags if flag != "instruction_suppression"]
