"""Structural phishing checks. These look at domains, links, and who the text is for.

A brand name, a bank field, or a sentence aimed at an assistant is a shape, not a
phrase copied from one mailbox. Mentioning an IBAN inside a real project, or
correcting an earlier figure, is not one of those shapes. Text is folded
(NFKC and confusables) before the checks run, and hidden HTML is included.
"""

from __future__ import annotations

import os
import re

from app.normalize import fold, open_channels

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
    "upwork": ("upwork.com",),
    "linkedin": ("linkedin.com",),
    "dropbox": ("dropbox.com",),
    "intuit": ("intuit.com",),
    "quickbooks": ("quickbooks.com", "intuit.com"),
    "zoom": ("zoom.us", "zoom.com"),
    "coinbase": ("coinbase.com",),
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
    "pm.me",
    "gmx.com",
    "gmx.de",
    "yandex.com",
    "yandex.ru",
    "qq.com",
    "163.com",
    "mail.ru",
    "tuta.com",
    "tutanota.com",
    "zoho.com",
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
# An order aimed at the assistant. A buyer who wants "an AI assistant" and
# names a budget is a lead, not an instruction.
_ADDRESSED = re.compile(
    r"\b(?:ai |the )?(?:assistant|language model)\b\s*[:,]\s*.{0,200}?\b"
    r"(?:ignore|disregard|classify|override|mark|set|update|approve|file|skip|auto-send)\b",
    re.IGNORECASE | re.DOTALL,
)
_OVERRIDE = re.compile(
    r"\b(?:ignore|disregard|override|bypass)\b[^.\n]{0,60}\b"
    r"(?:rules|instructions|policy|guidelines|previous|prior|safeguards)\b",
    re.IGNORECASE,
)
_BANK_VERIFY = re.compile(
    r"\b(?:please\s+)?(?:verify|confirm|validate|update)\b[^.\n]{0,48}\b(?:your\s+)?"
    r"(?:bank(?:ing)?(?:\s+account)?|payout(?:\s+account)?|payment\s+method)\b"
    r"|\b(?:payment|payout|funds)\b[^.\n]{0,40}\b(?:on hold|suspended|locked)\b"
    r"[^.\n]{0,80}\b(?:verify|confirm|release|http)\b",
    re.IGNORECASE,
)
_SQUAT_LABEL = re.compile(
    r"payments?|payouts?|billing|invoices?|secure-?login|verify",
    re.IGNORECASE,
)
# A payment-shaped note that also asks the reader to verify, release funds,
# or pay through a link. The words are the shape, not one mailbox's copy.
_PAYMENT_SHAPE = re.compile(
    r"\b(?:invoices?|withdrawals?|payouts?|payments?|amount due|past due|overdue|remittance)\b",
    re.IGNORECASE,
)
_PAY_LURE = re.compile(
    r"\b(?:verify|confirm|validate|update)\b[^.\n]{0,80}\b(?:your\s+)?"
    r"(?:withdrawal(?:\s+method)?|payout(?:\s+method)?|bank(?:ing)?(?:\s+account)?|"
    r"payment\s+method|billing\s+details)\b"
    r"|\brelease\s+(?:the\s+)?funds\b"
    r"|\b(?:pay|payment|invoice)\b[^.\n]{0,60}\bsecure\s+link\b"
    r"|\bsecure\s+link\b[^.\n]{0,60}\b(?:pay|payment|invoice)\b"
    r"|\bpay\b[^.\n]{0,48}\b(?:via|using|through)\b[^.\n]{0,32}\b(?:secure\s+)?link\b",
    re.IGNORECASE,
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
# Money movement and payee changes. A project that merely mentions an IBAN is not
# one of these: the words have to be a rail, a payee, or a request to change where
# money goes.
_PAYMENT_INVARIANT = re.compile(
    r"\b("
    r"wallets?|crypto(?:currency)?|usdt|tether|bitcoin|btc|ethereum|"
    r"payees?|beneficiar(?:y|ies)|gift\s*cards?|store\s+cards?|claim[-\s]?codes?|"
    r"(?:app\s*store|itunes|google\s*play|play\s*store)\s+(?:gift\s*)?(?:cards?|codes?)|"
    r"routing\s+numbers?|account\s+numbers?|"
    r"card\s+numbers?|credit\s+cards?|debit\s+cards?|"
    r"update\s+our\s+details|pay(?:able)?\s+to|remit\s+to"
    r")\b",
    re.IGNORECASE,
)
# Where payable documents go. The shape is a routing verb, a document, and a
# destination (an address, "instead", or a replaced mailbox). It is not a list
# of sentences. An added CC is removed before this runs.
_PAYABLE_DOC = (
    r"(?:invoices?|receipts?|payments?|statements?|bills?|remittances?|"
    r"disbursements?|payouts?|(?:supplier|vendor)\s+bills?|"
    r"(?:ap|a/p|accounts[\s-]+payable)\s+correspondence)"
)
_ROUTE_VERB = r"(?:send|e-?mail|forward|direct|route|deliver|remit|redirect|mail|re-?route)"
_DEST_MARK = (
    r"(?:[\w.+-]+@[\w.-]+|"
    r"\binstead\b|"
    r"\b(?:new|updated|different|replacement|revised)\s+(?:e-?mail|address|inbox|mailbox)\b)"
)
_DESTINATION_ROUTE = re.compile(
    rf"\b{_ROUTE_VERB}\b.{{0,80}}\b{_PAYABLE_DOC}\b.{{0,50}}\b(?:to|at)\b[^.\n]{{0,80}}?{_DEST_MARK}"
    rf"|\b{_PAYABLE_DOC}\b.{{0,40}}\b(?:to|at)\b[^.\n]{{0,80}}?{_DEST_MARK}",
    re.IGNORECASE | re.DOTALL,
)
_BILLING_MAILBOX = re.compile(
    r"\b(?:new|updated|replacement|revised)\s+(?:billing|remittance|payment|invoice)\s+e-?mails?\b"
    r"|\b(?:billing|remittance|payment|invoice)\s+e-?mails?\s+is\b"
    r"|\b(?:update|change|switch)\b.{0,30}\b(?:ap|a/p|accounts[\s-]+payable)\s+contacts?\b"
    r"|\b[\w.+-]+@[\w.-]+[^.\n]{0,48}\b(?:invoice|receipt|payment|statement|bill)\s+delivery\b",
    re.IGNORECASE | re.DOTALL,
)
# "cc our AP" / "cc ap@…" is an added copy, not a new destination.
_ADDITIVE_CC = re.compile(
    r"\bcc\b.{0,80}\b(?:ap@[\w.-]*|ap\b|a/p\b|accounts[\s-]+payable)\b",
    re.IGNORECASE | re.DOTALL,
)
_PAYEE_SHIFT = re.compile(
    r"\b(?:new|updated|update|change|changed|different|instead|revised|replacement)\b"
    r".{0,50}\b(?:bank\s+accounts?|"
    r"accounts?(?!\s+(?:manager|executive|team|director|owner|rep|payable|plan|plans))|"
    r"payees?|beneficiar(?:y|ies)|routing|banks?|wallets?)\b"
    r"|"
    r"\b(?:payees?|wallets?|beneficiar(?:y|ies))\b.{0,40}\b(?:instead|updated|changed)\b",
    re.IGNORECASE | re.DOTALL,
)
_NEW_PAYABLE_ACCOUNT = re.compile(
    r"\b(?:pay(?:able)?\s+to|banking\s+details|account\s+number|"
    r"new\s+(?:payee|details)|"
    r"new\s+(?:bank\s+)?accounts?(?!\s+(?:manager|executive|team|director|owner|rep|plan|plans|payable)))\b",
    re.IGNORECASE,
)
# A bank or institution move, in either order, including the same shape in
# Spanish and French. "no change" is removed before this runs.
_BANK_NOUN = (
    r"(?:banks?|banking|institutions?|banco|banque|bancos|"
    r"bancaires?|bancari[oa]s?|entidad(?:es)?|instituci[oó]n(?:es)?|"
    r"coordonn[ée]es|rib)"
)
_BANK_VERB = (
    r"(?:chang(?:e|ed|es|ing|é|ée|ées|ement|ements)?|"
    r"mov(?:e|ed|es|ing)|migrat(?:e|ed|es|ing|ion)|switch(?:ed|es|ing)?|"
    r"cambi(?:o|ó|amos|ado|aron|ar|a|é)|modifi(?:é|ée|ées|er)|"
    r"replac(?:e|ed|es|ing)|updat(?:e|ed|es|ing))"
)
_BANK_MOVE = re.compile(
    rf"\b{_BANK_VERB}\b.{{0,40}}\b{_BANK_NOUN}\b|\b{_BANK_NOUN}\b.{{0,40}}\b{_BANK_VERB}\b",
    re.IGNORECASE | re.DOTALL,
)
_PAYMENTS_NOW = re.compile(
    r"\b(?:payments?|funds|wires?|money|pagos?|fonds|virements?)\b.{0,40}"
    r"\b(?:now|no longer|ahora|ya no|maintenant|d[ée]sormais)\b.{0,40}"
    r"\b(?:go|goes|going|sent|send|paid|pay|van|vont|ir[aá]n?)\b"
    r"|"
    r"\b(?:now|no longer|ahora|ya no|maintenant|d[ée]sormais)\b.{0,30}"
    r"\b(?:go|goes|going|sent|van|vont)\b.{0,40}"
    r"\b(?:account|bank|factor|institution|partner|cuenta|compte)\b",
    re.IGNORECASE | re.DOTALL,
)
_PRIOR_STATE = re.compile(
    r"\b(?:instead|no longer|previously|previous|former|moved|migrat\w+|replac\w+|"
    r"chang\w+|updated|update|revised|different|switch\w*|from now on|going forward|"
    r"redirect(?:ed|ing)?|re-?rout\w+)\b"
    r"|\bnew\s+(?:billing|remittance|payment|invoice|bank|account|address|e-?mail)\b",
    re.IGNORECASE,
)
_AP_ADDRESS = re.compile(
    r"\b(?:ap|a/p|accounts[\s-]+payable|billing)\s+(?:e-?mail|address)\s+is\b",
    re.IGNORECASE,
)
# A reassurance that nothing moved. It must not itself become the bank-change hit.
_REASSURANCE = re.compile(
    r"[^.!\n]*\b(?:no|not|without|n't)\b[^.!\n]{0,48}\bchang\w+\b[^.!\n]*"
    r"|[^.!\n]*\bunchanged\b[^.!\n]*"
    r"|[^.!\n]*\b(?:remain|stays?|stay)\s+the\s+same\b[^.!\n]*",
    re.IGNORECASE,
)
_ENCLOSED_ACCOUNT = re.compile(
    r"\b(?:route|send|direct|pay|forward)\b.{0,50}\b(?:payments?|funds|money|wires?)\b"
    r".{0,60}\baccounts?\b.{0,40}\b(?:attach\w*|enclos\w*|letter|note)\b",
    re.IGNORECASE | re.DOTALL,
)
# Account details sitting in an attachment, with no routing verb required.
_ENCLOSED_DETAILS = re.compile(
    r"\b(?:account|banking|payment|remittance)\s+details\b.{0,60}"
    r"\b(?:enclos\w+|attach\w*|letter|notice)\b"
    r"|\b(?:enclos\w+|attach\w*|letter|notice)\b.{0,60}"
    r"\b(?:account|banking|payment|remittance)\s+details\b",
    re.IGNORECASE | re.DOTALL,
)
# A factor or factoring partner taking over payment. "two-factor" and "key factor" do not match.
_FACTORING_SHIFT = re.compile(
    r"\bfactoring\b"
    r"|(?<![\w-])factors?(?![\w-]).{0,48}\b(?:payments?|invoices?|settle|receivables)\b"
    r"|\b(?:payments?|invoices?|settle|receivables)\b.{0,48}(?<![\w-])factors?(?![\w-])",
    re.IGNORECASE | re.DOTALL,
)
# An enrollment or authorization form for ACH or direct deposit. "paid via ACH" is not one.
_ACH_ENROLL = re.compile(
    r"\bach\b.{0,60}\b(?:enrollment|enrolment|authori[sz]\w*|sign-?up|form)\b"
    r"|\b(?:enroll\w*|enrol\w*|authori[sz]\w*|sign-?up)\b.{0,60}\b(?:ach|direct\s+deposit)\b",
    re.IGNORECASE | re.DOTALL,
)
_LOCKBOX_CHANGE = re.compile(
    r"\bnew\s+lock\s*box(?:es)?\b"
    r"|\block\s*box(?:es)?\b.{0,40}\b(?:chang\w+|mov\w+|updat\w+|switch\w*|instead|replac\w+|no longer)\b"
    r"|\b(?:chang\w+|mov\w+|updat\w+|switch\w*|instead|replac\w+)\b.{0,40}\block\s*box(?:es)?\b",
    re.IGNORECASE | re.DOTALL,
)
_CONSUMER_RAIL = r"(?:zelle|venmo|cash\s*app|cashapp)"
_RAIL_ASK = re.compile(
    rf"\b(?:send|pay|transfer|route|forward|direct|settle)\b.{{0,60}}\b{_CONSUMER_RAIL}\b"
    rf"|\b{_CONSUMER_RAIL}\b.{{0,48}}(?:@\w+|\b(?:to|at|phone|number|handle|me)\b)"
    rf"|\b(?:zelle|venmo)\s+me\b"
    rf"|\b{_CONSUMER_RAIL}\b[^.\n]{{0,40}}(?:\+?\d[\d\s().-]{{6,}}\d)"
    rf"|\bcash\s*app\b.{{0,24}}\$[A-Za-z][A-Za-z0-9_]{{1,20}}\b"
    rf"|\$[A-Za-z][A-Za-z0-9_]{{1,20}}\b.{{0,30}}\bcash\s*app\b"
    rf"|\b(?:paypal\.me|venmo\.com/u|cash\.app)/[A-Za-z0-9._-]{{2,}}",
    re.IGNORECASE | re.DOTALL,
)
# A receipt or a service notification. Stripped before the rail ask is read.
_RAIL_NOTICE = re.compile(
    r"[^.!\n]*\b(?:"
    r"receipts?|received|you(?:'ve| have)? paid|paid you|"
    r"(?:payment|transfer|money) (?:was |has been |is )?sent|"
    r"was sent|has been (?:sent|paid|deposited|received)|"
    r"on its way|confirmations?|notifications?|refund(?:ed)?|"
    r"you got paid|we(?:'ve| have) paid|has been paid"
    r")\b[^.!\n]*",
    re.IGNORECASE,
)
_IBAN_CANDIDATE = re.compile(
    r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b",
    re.IGNORECASE,
)
_BIC_LABELED = re.compile(
    r"\b(?:bic|swift)\b[^A-Za-z0-9]{0,16}([A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)\b",
    re.IGNORECASE,
)
_SORT_AND_ACCOUNT = re.compile(
    r"\b(\d{2}-\d{2}-\d{2})\b.{0,40}\b(\d{8})\b|\b(\d{8})\b.{0,40}\b(\d{2}-\d{2}-\d{2})\b",
    re.DOTALL,
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


def _damerau(left: str, right: str) -> int:
    """Edit distance, counting one adjacent transposition as a single edit."""
    if left == right:
        return 0
    if abs(len(left) - len(right)) > 1:
        return 2
    rows = len(left) + 1
    cols = len(right) + 1
    dist = [[0] * cols for _ in range(rows)]
    for i in range(rows):
        dist[i][0] = i
    for j in range(cols):
        dist[0][j] = j
    for i in range(1, rows):
        low = 2
        for j in range(1, cols):
            cost = 0 if left[i - 1] == right[j - 1] else 1
            dist[i][j] = min(dist[i - 1][j] + 1, dist[i][j - 1] + 1, dist[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and left[i - 1] == right[j - 2] and left[i - 2] == right[j - 1]:
                dist[i][j] = min(dist[i][j], dist[i - 2][j - 2] + 1)
            if dist[i][j] < low:
                low = dist[i][j]
        if low > 1:
            return 2
    return dist[-1][-1]


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
    return _brand_typosquat(folded)


def _brand_typosquat(domain: str) -> bool:
    """One edit, or one adjacent swap, from a known brand label. Short brands are skipped."""
    if not domain or "." not in domain:
        return False
    tokens: list[str] = []
    for part in re.split(r"[.\-]", domain):
        if len(part) < 5:
            continue
        tokens.append(part)
        leet = part.translate(_LEET)
        if leet != part:
            tokens.append(leet)
    for token in tokens:
        for brand, suffixes in _BRANDS.items():
            if len(brand) < 5 or _legit(domain, suffixes):
                continue
            if brand in token:
                continue
            if abs(len(token) - len(brand)) > 1:
                continue
            if _damerau(token, brand) <= 1:
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
    # A vendor footer that only prints a sort code and an account number is a
    # payment detail for the filing gate, not a claim the message is phishing.
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
    if _OVERRIDE.search(text or ""):
        return True
    if _ADDRESSED.search(text or ""):
        return True
    return _machine_payload(text or "")


def _registrable_label(domain: str) -> str:
    parts = [part for part in (domain or "").lower().strip(".").split(".") if part]
    if len(parts) >= 3 and parts[-2] in {"co", "com", "org", "net", "ac"} and len(parts[-1]) == 2:
        return parts[-3]
    if len(parts) >= 2:
        return parts[-2]
    return parts[0] if parts else ""


def known_contact_lookalike(domain: str, known_contacts: list[dict] | None) -> bool:
    """A domain one edit from a contact already in this mailbox, not a brand list."""
    label = fold(_registrable_label(domain)).translate(_LEET)
    if len(label) < 8 or not known_contacts:
        return False
    own = (domain or "").lower().strip(".")
    for contact in known_contacts:
        other_domain = _domain(contact.get("email") or "")
        if not other_domain or other_domain == own:
            continue
        other = fold(_registrable_label(other_domain)).translate(_LEET)
        if len(other) < 8 or other == label or abs(len(other) - len(label)) > 1:
            continue
        if _edit_distance(label, other) <= 1:
            return True
    return False


def _squat_host(host: str) -> bool:
    """payments.example or brand-payments.example, and not a real brand domain."""
    domain = (host or "").lower().strip(".")
    if not domain or "." not in domain:
        return False
    for suffixes in _BRANDS.values():
        if _legit(domain, suffixes):
            return False
    return bool(_SQUAT_LABEL.search(_registrable_label(domain)))


def _credential_request(text: str, sender: str) -> bool:
    if _BANK_VERIFY.search(text or "") and (_urls(text or "") or _squat_host(_domain(sender))):
        return True
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


def _strip_additive_cc(text: str) -> str:
    """Drop an added AP copy so it is not read as the new payee."""
    return _ADDITIVE_CC.sub(" ", text or "")


def _without_reassurance(text: str) -> str:
    """Drop a clause that says the bank details did not change."""
    return _REASSURANCE.sub(" ", text or "")


def _iban_valid(token: str) -> bool:
    compact = re.sub(r"\s+", "", token).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", compact):
        return False
    if not 15 <= len(compact) <= 34:
        return False
    moved = compact[4:] + compact[:4]
    digits = "".join(str(int(char, 36)) for char in moved)
    return int(digits) % 97 == 1


def _aba_valid(nine: str) -> bool:
    if not re.fullmatch(r"\d{9}", nine) or nine == "000000000":
        return False
    weights = (3, 7, 1, 3, 7, 1, 3, 7, 1)
    total = sum(int(digit) * weight for digit, weight in zip(nine, weights))
    return total % 10 == 0


def _routing_and_account(text: str) -> bool:
    """A 9-digit ABA routing number beside a separate account number."""
    digits = [(match.group(0), match.start(), match.end()) for match in re.finditer(r"\d{9}", text)]
    accounts = [
        (match.start(), match.end())
        for match in re.finditer(r"\d{6,17}", text)
        if len(match.group(0)) != 9
    ]
    for number, start, end in digits:
        if not _aba_valid(number):
            continue
        for account_start, account_end in accounts:
            if account_end <= start or account_start >= end:
                if min(abs(account_start - end), abs(start - account_end)) <= 80:
                    return True
    return False


def _account_shapes(text: str) -> bool:
    """A real IBAN, a labeled BIC, a US routing-and-account pair, or a UK sort code and account."""
    upper = text.upper()
    if any(_iban_valid(match.group(0)) for match in _IBAN_CANDIDATE.finditer(upper)):
        return True
    if _BIC_LABELED.search(upper):
        return True
    if _routing_and_account(text):
        return True
    return bool(_SORT_AND_ACCOUNT.search(text))


def _payable_destination(text: str) -> bool:
    return bool(_DESTINATION_ROUTE.search(text) or _AP_ADDRESS.search(text))


def _destination_change(text: str) -> bool:
    """A change of an existing payee or invoice destination.

    Naming where a new client wants invoices sent, with no prior account to
    replace, is not this. A replaced billing mailbox, an updated AP contact,
    or a route that says instead, new, or no longer, is.
    """
    stripped = _without_reassurance(_strip_additive_cc(text or ""))
    if _BILLING_MAILBOX.search(stripped):
        return True
    for match in _DESTINATION_ROUTE.finditer(stripped):
        window = stripped[max(0, match.start() - 80) : match.end() + 80]
        if _PRIOR_STATE.search(window):
            return True
    return False


def invoice_address_notice(text: str) -> bool:
    """A first statement of where invoices go. A person can confirm it."""
    folded = fold(text or "")
    stripped = _without_reassurance(_strip_additive_cc(folded))
    if _destination_change(folded):
        return False
    return _payable_destination(stripped)


def _bank_change(text: str) -> bool:
    cleaned = _without_reassurance(text or "")
    return bool(_BANK_MOVE.search(cleaned) or _PAYMENTS_NOW.search(cleaned))


def _consumer_rail_request(text: str) -> bool:
    """Zelle, Venmo, Cash App, or a PayPal.me link used to ask for money.

    A receipt or a notification from the service is removed first, so
    "you received $40 on Venmo" is not a request.
    """
    cleaned = _RAIL_NOTICE.sub(" ", text or "")
    return bool(_RAIL_ASK.search(cleaned))


def _payment_destination_shift(text: str) -> bool:
    """A change of who gets paid that is not a bank-account number.

    Factoring, an ACH enrollment or authorization form, a lockbox move, and
    account details left in an enclosed notice. A paid-via-ACH receipt is not
    one of these.
    """
    cleaned = _without_reassurance(text or "")
    return bool(
        _FACTORING_SHIFT.search(cleaned)
        or _ACH_ENROLL.search(cleaned)
        or _LOCKBOX_CHANGE.search(cleaned)
        or _ENCLOSED_DETAILS.search(cleaned)
    )


def payment_related(text: str) -> bool:
    """True when the text moves money or changes where an existing payment goes.

    A valid IBAN, a labeled BIC or SWIFT code, a US account with an ABA routing
    number, or a UK sort code with an account number matches. So does a bank
    or institution change, including the same shape in Spanish or French, and
    a request to send a payment to the account in an attached letter. Asking
    a first contact, or a payment-change note, to pay by Zelle, Venmo, Cash
    App, or PayPal.me matches. A receipt or notification from those services
    does not. Factoring, an ACH enrollment form, a lockbox change, and account
    details in an enclosed notice match. A new client's AP address, with
    nothing being replaced, does not. A payout notice that only names the bank
    account it is already going to does not. Asking to also CC accounts
    payable does not, even when the note says the bank details are unchanged.
    The words IBAN or SWIFT, with no real code, do not.
    """
    folded = fold(text or "")
    cleaned = _without_reassurance(_strip_additive_cc(folded))
    if (
        _account_shapes(folded)
        or _ENCLOSED_ACCOUNT.search(folded)
        or _consumer_rail_request(folded)
        or _payment_destination_shift(folded)
    ):
        return True
    if _destination_change(folded) or _bank_change(folded):
        return True
    if _PAYMENT_INVARIANT.search(folded) or _PAYEE_SHIFT.search(cleaned):
        return True
    if re.search(
        r"\b(?:invoices?|receipts?|payments?|statements?|bills?)\b",
        folded,
        re.IGNORECASE,
    ) and _NEW_PAYABLE_ACCOUNT.search(cleaned):
        return True
    return bool(
        _payment_change(cleaned)
        or _WIRE_REQUEST.search(folded)
        or _RAIL_CHANGE.search(cleaned)
        or _GIFT.search(folded)
    )


def _known_contact_domain(domain: str, known_contacts: list[dict] | None) -> bool:
    if not domain or not known_contacts:
        return False
    for contact in known_contacts:
        if _domain(contact.get("email") or "") == domain:
            return True
    return False


def payment_lure(text: str, sender: str, known_contacts: list[dict] | None = None) -> bool:
    """Invoice, payout, or withdrawal mail that asks to verify, release funds, or pay via a link.

    A typo-squat of a known brand, a generic invoice or billing host, or any
    other sender domain that is not a known contact, makes that request
    suspicious. A real brand's own domain, and a domain already in the CRM,
    are left to the other checks.
    """
    folded = fold(text or "")
    if not (_PAYMENT_SHAPE.search(folded) and _PAY_LURE.search(folded)):
        return False
    domain = _domain(sender)
    hosts = [host for host in (domain, *_urls(folded)) if host]
    if any(lookalike_domain(host) or _squat_host(host) for host in hosts):
        return True
    if not domain or _known_contact_domain(domain, known_contacts):
        return False
    if any(_legit(domain, suffixes) for suffixes in _BRANDS.values()):
        return False
    return True


def assess_risk(email: dict, text: str, raw: str = "", known_contacts: list[dict] | None = None) -> list[str]:
    """Return risk flags. A suppression note is recorded and does not force the category."""
    flags: list[str] = []
    body = raw or email.get("body") or ""
    channels = open_channels(body)
    hidden = channels.concealed
    combined = fold(f"{email.get('subject') or ''}\n{text}\n{hidden}")
    sender = email.get("from_email") or ""
    raw_hosts = [host.lower().split(":")[0] for host in _URL.findall(body)]
    sender_domain = _domain(sender)
    hosts = [sender_domain, *raw_hosts]
    if lookalike_domain(sender) or any(lookalike_domain(host) for host in raw_hosts):
        flags.append("lookalike_domain")
    elif any(known_contact_lookalike(host, known_contacts) for host in hosts if host) and (
        _WIRE_REQUEST.search(combined)
        or _BANK_VERIFY.search(combined)
        or _credential_ask(combined)
        or re.search(r"\b(?:wire|transfer)\b", combined, re.IGNORECASE)
    ):
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
    if payment_lure(combined, sender, known_contacts):
        flags.append("payment_lure")
    if _DANGEROUS_FILE.search(combined) or _DANGEROUS_FILE.search(body or ""):
        flags.append("dangerous_attachment")
    if channels.obfuscated:
        flags.append("obfuscated_text")
    if channels.concealed_instruction:
        flags.append("concealed_instruction")
    if hidden and _HIDDEN_INSTRUCTION.search(hidden):
        flags.append("prompt_injection")
    elif _assistant_instruction(combined):
        flags.append("prompt_injection")
    elif _SUPPRESSION.search(combined):
        flags.append("instruction_suppression")
    if payment_related(combined):
        flags.append("payment_related")
    return flags


def hard_flags(flags: list[str]) -> list[str]:
    """Flags that force the suspicious label.

    A note that only says "do not alert" is recorded and ignored, so a real
    outage cannot hide behind it. payment_related is a filing block and a
    banner, not a claim that the message is phishing.
    """
    soft = {"instruction_suppression", "payment_related"}
    return [flag for flag in flags if flag not in soft]


def money_movement(text: str) -> bool:
    """A request to move money or to change where it goes. A receipt is not one."""
    return payment_related(text)


def blocks_autofile(email: dict, text: str, flags: list[str], budget: str | None, category: str) -> bool:
    """Money movement and uncertain mail are never written to the CRM on their own.

    A free-mail sender with a price and a request to pay, wire, or change an
    account is blocked. So is any message that changes a wire, ACH, routing
    number, or bank detail, even when a model called it a lead.
    """
    if category in {"spam", "suspicious", "review", "recruiter"}:
        return True
    if hard_flags(flags) or "budget_not_in_body" in flags:
        return True
    folded = fold(text or "")
    if payment_related(folded):
        return True
    if free_mail(email.get("from_email") or "") and budget and re.search(
        r"\b(wire|transfer|ach|routing|bank details|account number)\b", folded, re.I
    ):
        return True
    return False
