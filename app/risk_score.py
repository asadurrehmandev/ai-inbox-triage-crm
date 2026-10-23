"""Feature score for phishing. The decision is the combination, not a phrase.

Features are structural: who the domain is, whether a free-mail account is
wearing a company name, edit distance to a known contact or brand, a link
that leaves the sender's domain, a shortener, a money-movement ask, and
urgency pressure. A logistic model trained on synthetic feature rows scores
them. Money movement plus a risky sender or a mismatched link is suspicious
on its own, including when the logistic score is quiet.
"""

from __future__ import annotations

import re

from app.heads import ask_threshold, money_threshold, risk_probability, risk_threshold
from app.normalize import fold
from app.risk import (
    _BRANDS,
    _LEET,
    _URL,
    _bank_change,
    _domain,
    _edit_distance,
    _legit,
    _registrable_label,
    borrowed_credential_link,
    free_mail,
    deceptive_pay_link,
    lookalike_domain,
)

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
}
_PAY_WINDOW = re.compile(
    r"\b(?:pay|payment|transfer|verify|withdraw(?:al)?|payout|wallet|gift|invoice|überweis|virer|pagar)\b",
    re.IGNORECASE,
)
_GIFT_CRYPTO = re.compile(
    r"\b(?:gift\s*cards?|store\s*cards?|usdt|tether|bitcoin|btc|ethereum|seed phrase|crypto\s*wallet)\b",
    re.IGNORECASE,
)
_IBAN_WORD = re.compile(r"\biban\b|\bswift\b|\bbic\b", re.IGNORECASE)
# A project budget or a quote is not this. Money similarity counts only with a cue.
_MONEY_CUE = re.compile(
    r"\b(?:pay|payment|payments|transfer|wire|wiring|withdraw(?:al)?|payout|wallet|"
    r"invoice|remittance|iban|swift|bic|routing|sort code|"
    r"gift\s*cards?|password|credentials?|login|sign[\s-]?in|"
    r"überweis|virer|pagar|banco|banque|banks?|banking)\b",
    re.IGNORECASE,
)
_BANK_CUE = re.compile(
    r"\b(?:banks?|banking|iban|swift|bic|routing|sort code|account number)\b",
    re.IGNORECASE,
)
_CREDENTIAL_CUE = re.compile(
    r"\b(?:password|credentials?|login|sign[\s-]?in|one-time code|passcode)\b",
    re.IGNORECASE,
)
_PLAIN_INVOICE = re.compile(
    r"\b(?:amount due|balance due|invoice\s*#?\s*\d+|inv-\d+|past due|remittance|payment received)\b",
    re.IGNORECASE,
)


def _hosts(text: str) -> list[str]:
    found = []
    for host in _URL.findall(text or ""):
        cleaned = fold(host).lower().split(":")[0].strip(".")
        if cleaned:
            found.append(cleaned)
    return found


def _registrable(domain: str) -> str:
    return _registrable_label(domain or "")


def _tokens(value: str) -> list[str]:
    return [part for part in re.split(r"[^a-z0-9]+", fold(value or "").lower()) if len(part) >= 5]


def _near(left: str, right: str) -> bool:
    """Edit distance up to 2 on longer labels, and 1 on shorter ones."""
    if not left or not right or left == right:
        return False
    if min(len(left), len(right)) < 5:
        return False
    limit = 2 if min(len(left), len(right)) >= 8 else 1
    if abs(len(left) - len(right)) > limit:
        return False
    return _edit_distance(left, right) <= limit


def _brand_hit(domain: str) -> bool:
    if lookalike_domain(domain):
        return True
    if not domain or "." not in domain:
        return False
    folded = fold(domain).lower()
    labels = [part.translate(_LEET) for part in re.split(r"[.\-]", folded) if len(part) >= 5]
    for label in labels:
        for brand, suffixes in _BRANDS.items():
            if _legit(folded, suffixes):
                continue
            if brand in label or _near(label, brand):
                return True
    return False


def _contact_hit(domain: str, contacts: list[dict] | None) -> bool:
    if not domain or not contacts:
        return False
    own = domain.lower().strip(".")
    labels = [part.translate(_LEET) for part in re.split(r"[.\-]", fold(own)) if len(part) >= 5]
    labels.append(fold(_registrable(own)).translate(_LEET))
    for contact in contacts:
        other = _domain(contact.get("email") or "")
        if not other or other == own:
            continue
        other_label = fold(_registrable(other)).translate(_LEET)
        company_tokens = _tokens(str(contact.get("company") or ""))
        candidates = [other_label, *company_tokens]
        for candidate in candidates:
            if len(candidate) < 5:
                continue
            for label in labels:
                if _near(label, candidate) or (candidate in label and not _legit(own, (other,))):
                    if label != candidate:
                        return True
    return False


def _known_domain(domain: str, contacts: list[dict] | None) -> bool:
    if not domain or not contacts:
        return False
    for contact in contacts:
        if _domain(contact.get("email") or "") == domain:
            return True
    return False


def _claims_org(email: dict, contacts: list[dict] | None) -> bool:
    """A free-mail account wearing a company, a vendor, or a known person."""
    sender = email.get("from_email") or ""
    if not free_mail(sender):
        return False
    local = sender.split("@", 1)[0]
    blob = set(_tokens(local) + _tokens(email.get("from_name") or ""))
    display = fold(email.get("from_name") or "").casefold().strip()
    if re.search(r"\b(?:inc|llc|ltd|gmbh|corp|company|billing|accounts)\b", display, re.IGNORECASE):
        return True
    for contact in contacts or []:
        if display and display == fold(contact.get("name") or "").casefold().strip() and display:
            return True
        for token in _tokens(str(contact.get("company") or "")) + _tokens(_registrable(_domain(contact.get("email") or ""))):
            if token in blob or any(token in part or part in token for part in blob if len(part) >= 5):
                return True
    return False


def _aligned(domain: str, text: str, lookalike: bool) -> bool:
    """The sender domain is the organization named in the message, on that domain."""
    if not domain or free_mail("user@" + domain) or lookalike:
        return False
    label = re.sub(r"[^a-z0-9]", "", fold(_registrable(domain)).lower())
    if len(label) < 5:
        return False
    compact = re.sub(r"[^a-z0-9]", "", fold(text or "").lower())
    return label in compact


def _link_mismatch(sender_domain: str, hosts: list[str]) -> bool:
    own = re.sub(r"[^a-z0-9]", "", _registrable(sender_domain))
    for host in hosts:
        if host in _SHORTENERS:
            continue
        other = re.sub(r"[^a-z0-9]", "", _registrable(host))
        if other and own and other != own:
            return True
    return False


def _pay_off_domain(text: str, sender_domain: str, hosts: list[str]) -> bool:
    """A pay, verify, or invoice link whose host is not the sender, or a shortener beside one."""
    own = re.sub(r"[^a-z0-9]", "", _registrable(sender_domain))
    body = text or ""
    for match in _URL.finditer(body):
        host = fold(match.group(1)).lower().split(":")[0].strip(".")
        window = body[max(0, match.start() - 80) : match.end() + 40]
        short = host in _SHORTENERS or any(host == item or host.endswith("." + item) for item in _SHORTENERS)
        other = re.sub(r"[^a-z0-9]", "", _registrable(host))
        off = bool(other and own and other != own)
        if (short or off) and _PAY_WINDOW.search(window):
            return True
    return False


def _money_cue(text: str) -> bool:
    """Pay, invoice, bank, or credential language. A budget or a quote is not a cue."""
    body = text or ""
    return bool(
        _MONEY_CUE.search(body)
        or _PAY_WINDOW.search(body)
        or _IBAN_WORD.search(body)
        or _GIFT_CRYPTO.search(body)
    )


def _plain_letterhead(text: str, pay_off: bool) -> bool:
    if pay_off or _GIFT_CRYPTO.search(text or ""):
        return False
    return bool(_PLAIN_INVOICE.search(text or ""))


def features(email: dict, text: str, contacts: list[dict] | None, money_sim: float = 0.0) -> dict[str, float]:
    sender = email.get("from_email") or ""
    domain = _domain(sender)
    hosts = _hosts(text)
    lookalike = _brand_hit(domain) or any(_brand_hit(host) for host in hosts) or _contact_hit(domain, contacts)
    for host in hosts:
        if _contact_hit(host, contacts):
            lookalike = True
    shortener = any(host in _SHORTENERS or host.endswith("." + item) for host in hosts for item in _SHORTENERS)
    mismatch = _link_mismatch(domain, hosts)
    pay_off = _pay_off_domain(text, domain, hosts)
    aligned = _aligned(domain, f"{email.get('from_name') or ''}\n{text}", lookalike) or _known_domain(domain, contacts)
    claims = _claims_org(email, contacts)
    risky = bool(free_mail(sender) or lookalike or mismatch or shortener or claims or not aligned)
    money = 0.0
    if pay_off or _GIFT_CRYPTO.search(text or ""):
        money = 1.0
    elif _IBAN_WORD.search(text or "") and risky and not aligned:
        money = 1.0
    elif (
        money_sim >= money_threshold()
        and not _plain_letterhead(text, pay_off)
        and _money_cue(text)
        and (lookalike or shortener or bool(_PAY_WINDOW.search(text or "")) or bool(_IBAN_WORD.search(text or "")))
    ):
        money = 1.0
    urgency = 1.0 if re.search(
        r"\b(?:immediately|right away|asap|urgent|within \d+ hours?|final notice|sofort|urgente|acil)\b",
        text or "",
        re.IGNORECASE,
    ) else 0.0
    return {
        "known": 1.0 if _known_domain(domain, contacts) else 0.0,
        "free_mail": 1.0 if free_mail(sender) else 0.0,
        "claims_org": 1.0 if claims else 0.0,
        "lookalike": 1.0 if lookalike else 0.0,
        "link_mismatch": 1.0 if mismatch else 0.0,
        "shortener": 1.0 if shortener else 0.0,
        "money": money,
        "urgency": urgency,
        "aligned": 1.0 if aligned else 0.0,
        "money_sim": float(money_sim),
    }


def decide_suspicious(email: dict, text: str, contacts: list[dict] | None, signals: dict | float | None = None) -> bool:
    """An ask to move money, change a bank, or give credentials, plus a structural risk.

    The ask may come from the learned head, so it is not an English word list.
    Money similarity on a project budget or a quote is not an ask. It counts
    only together with a pay, invoice, bank, or credential cue, and only then
    can an unknown-domain link or a shortener force suspicious.
    A plain invoice on the sender's own domain, including a footer that only
    prints the account it is already paid to, is not suspicious.
    """
    if isinstance(signals, dict):
        money_sim = float(signals.get("money_sim") or 0.0)
        bank_sim = float(signals.get("bank_sim") or 0.0)
        credential_sim = float(signals.get("credential_sim") or 0.0)
    else:
        money_sim = float(signals or 0.0)
        bank_sim = 0.0
        credential_sim = 0.0
    sender = email.get("from_email") or ""
    # A bank-detail change is suspicious in every claimed language, before a
    # soft confirm and before an aligned letterhead can clear it.
    if _bank_change(text):
        return True
    # A credential link on someone else's private domain outranks urgent.
    if borrowed_credential_link(text, sender):
        return True
    # A lookalike or child-domain pay link is suspicious before any soft confirm.
    if deceptive_pay_link(text, sender, contacts):
        return True
    row = features(email, text, contacts, money_sim)
    reply = str(email.get("reply_to") or email.get("reply-to") or "")
    reply_domain = _domain(reply) if "@" in reply else ""
    sender_domain = _domain(email.get("from_email") or "")
    reply_mismatch = bool(reply_domain and sender_domain and reply_domain != sender_domain)
    structural = bool(
        row["free_mail"]
        or row["lookalike"]
        or row["link_mismatch"]
        or row["shortener"]
        or row["claims_org"]
        or reply_mismatch
    )
    if row["aligned"] and not structural:
        return False
    # A warm money head on a budget is not enough. Pair each head with its cue.
    ask = bool(
        row["money"] >= 1.0
        or (money_sim >= ask_threshold() and _money_cue(text))
        or (bank_sim >= ask_threshold() and bool(_BANK_CUE.search(text or "")))
        or (credential_sim >= ask_threshold() and bool(_CREDENTIAL_CUE.search(text or "")))
    )
    if ask and structural:
        return True
    if row["money"] >= 1.0 and risk_probability(row) >= risk_threshold():
        return True
    return False
