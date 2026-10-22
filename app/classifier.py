"""Rule engine used when no model key is set, and as the visible fallback.

Patterns are general (outages, invoices, proposals, promotions). They are not
a word list copied from the sample mailbox. Phishing and injection are decided
in app.risk before any category score is trusted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.budget import extract_budget
from app.heads import assess
from app.prepare import head_and_tail, hidden_text, html_to_text, strip_injection_notes, strip_quotes, unwrap_forward
from app.rank import settle
from app.risk import assess_risk, free_mail, hard_flags, known_contact_lookalike, payment_related
from app.risk_score import decide_suspicious

CATEGORIES = ("lead", "support", "invoice", "spam", "urgent", "suspicious", "review", "recruiter")

_CLOSINGS = re.compile(
    r"^(thanks|thank you|best regards|kind regards|warm regards|many thanks|best|regards|sincerely|cheers|warmly|cordialement|saludos|mit freundlichen grüßen),?\s*$",
    re.IGNORECASE,
)
_ROLE = {
    "accounts",
    "payable",
    "team",
    "support",
    "billing",
    "admin",
    "ops",
    "info",
    "sales",
    "marketing",
    "noreply",
    "no-reply",
    "newsletter",
    "notification",
    "notifications",
    "office",
    "bot",
    "mailer",
    "rewards",
    "desk",
    "security",
    "system",
    "notice",
    "mail",
}
_HONORIFICS = {"dr", "mr", "mrs", "ms", "prof", "phd"}
_TITLE_TAIL = {
    "director",
    "manager",
    "officer",
    "counsel",
    "controller",
    "founder",
    "president",
    "partner",
    "principal",
    "engineer",
    "accountant",
}
_TITLE_WORD = _TITLE_TAIL | {
    "head",
    "of",
    "the",
    "and",
    "vice",
    "chief",
    "senior",
    "junior",
    "assistant",
    "general",
    "medical",
    "operations",
    "managing",
}
_TITLE_PREFIX = re.compile(
    r"^(head of|vp of|vice president|director of|chief|medical director|general counsel)\b",
    re.IGNORECASE,
)
_JOB_LINE = re.compile(
    r"^(?:(?:senior|junior|lead|head|chief|medical|office|it|systems|associate|assistant|"
    r"general|managing|vice|operations|customer|account)\s+)*"
    r"(?:owner|founder|co-founder|coordinator|producer|associate|director|manager|officer|"
    r"controller|president|partner|principal|engineer|accountant|specialist|analyst|"
    r"consultant|counsel|supervisor|lead)$",
    re.IGNORECASE,
)
_COLD = re.compile(r"reply\s+stop", re.IGNORECASE)
_VENDOR = re.compile(r"(trial expires|upgrade now|your trial ends)", re.IGNORECASE)
_OOO = re.compile(
    r"^(out of office|automatic reply|auto-?reply|automatische antwort|respuesta autom[aá]tica|"
    r"r[ée]ponse automatique|resposta autom[aá]tica)\b|i am out of the office",
    re.IGNORECASE,
)
_OUTAGE = re.compile(
    r"\b(?:production is down|went down|is down|are down|outage|site down|sev-?1|p0|"
    r"offline|not responding|"
    r"can(?:not|'t) take bookings|unable to take bookings|"
    r"fora do ar|ca[ií]d[oa]|en panne|ausgefallen|hors service)\b"
    r"|宕机|障害が発生|サイトが(?:ダウン|落ち)",
    re.IGNORECASE,
)
_SERVICE = (
    r"system|systems|site|website|platform|checkout|booking|bookings|orders?|"
    r"shop|portal|service|servicio|sistema|pedidos|caisse|kassa|服务器|系统|サイト"
)
_DOWN_WORD = (
    r"offline|not working|isn'?t working|does(?:n'?t| not) work|stopped working|"
    r"no funciona|n[aã]o funciona|ne fonctionne pas|funktioniert nicht|"
    r"hors service|ca[ií]d[oa]|ausgefallen|fora do ar|en panne|çalışmıyor|calismiyor"
)
_NOT_URGENT = re.compile(
    r"\b(?:not urgent|no rush|no hurry|low priority|whenever you (?:can|have)|"
    r"when you have time|pas urgent|no es urgente|nicht dringend|acil de[gğ]il)\b",
    re.IGNORECASE,
)
_INVOICE_EVIDENCE = re.compile(
    r"\b(?:amount due|balance due|payment due|total due|please pay|kindly pay|"
    r"pay this invoice|invoice\s*#?\s*\d+|inv-\d+|past due|remittance|"
    r"payment received|your receipt|receipt for|order receipt|trip receipt|"
    r"importe pendiente|montant d[uû]|offene(?:r|n)? betrag|valor em aberto|"
    r"应付|請求書|お支払額)\b"
    r"|factura\s*(?:n[oº.]|no|#|\d)"
    r"|rechnung\s*(?:nr|#|\d)"
    r"|fatura\s*(?:n|#|\d)",
    re.IGNORECASE,
)
_RECRUITER = re.compile(
    r"\b(?:recruiter|talent (?:partner|acquisition|team)|"
    r"your (?:resume|cv)|open role|job opening|"
    r"this role pays|base salary|compensation range|\bote\b|"
    r"interview (?:process|for the role)|we(?:'re| are) hiring for)\b",
    re.IGNORECASE,
)
_SALARY = re.compile(
    r"\b(?:salary|compensation|\bote\b|per annum|annually|base pay)\b",
    re.IGNORECASE,
)
_REFERRAL = re.compile(
    r"\b(?:referred me|a referral|recommended you|suggested I (?:write|reach|contact)|"
    r"heard about you|gave me your (?:name|email))\b",
    re.IGNORECASE,
)
_COMMERCIAL = re.compile(
    r"\b(?:quote|quotation|proposal|retainer|budget|sow|statement of work|"
    r"scope of work|s[oö]zle[sş]me|合同|契約|bütçe|预算|予算|or[cç]amento|presupuesto|devis)\b",
    re.IGNORECASE,
)
_SUPPORTISH = re.compile(
    r"\b(?:not working|isn'?t working|does(?:n'?t| not) work|is broken|broken|bug|"
    r"can(?:not|'t) log ?in|cannot log ?in|password|login loop|feature request|"
    r"how do i|could you (?:add|fix|check)|stopped syncing|is not pushing|"
    r"no funciona|ne fonctionne pas|funktioniert nicht|çalışmıyor)\b",
    re.IGNORECASE,
)
_RENEWAL = re.compile(
    r"\b(?:domain|subscription|licen[cs]e|certificate|ssl|hosting|membership)\b"
    r".{0,40}\b(?:renew(?:al)?|expires?|expiry|expiration)\b"
    r"|\b(?:renew(?:al)?|expires?|expiry|expiration)\b.{0,40}"
    r"\b(?:domain|subscription|licen[cs]e|certificate|ssl|hosting|membership)\b",
    re.IGNORECASE | re.DOTALL,
)
_OVERDUE = re.compile(
    r"\b(?:past due|overdue|\d+\s+days?\s+(?:past|over)due|final notice|final demand)\b",
    re.IGNORECASE,
)
_NEWSLETTER = re.compile(
    r"\b(?:unsubscribe|opt out|manage preferences|newsletter|webinar)\b",
    re.IGNORECASE,
)
_HEADER_LINE = re.compile(r"^(?:from|to|cc|bcc|sent|date|subject)\s*:", re.IGNORECASE)
_COMPANY_SUFFIX = re.compile(
    r"\b(?:co|inc|ltd|llc|gmbh|corp|plc|sa|ag|bv|sarl|sas)\.$",
    re.IGNORECASE,
)
_REFUND = re.compile(
    r"\b(refund|charged twice|double[- ]charge|duplicate charge|billed twice)\b",
    re.IGNORECASE,
)


@dataclass
class Classification:
    category: str
    confidence: float
    name: str | None
    company: str | None
    budget: str | None
    intent: str
    draft_reply: str
    model: str = "rules"
    risk_flags: list[str] = field(default_factory=list)
    secondary_categories: list[str] = field(default_factory=list)
    forwarded_by: str | None = None
    contact_email: str | None = None
    llm_error: str | None = None
    model_suggestion: str | None = None
    suggested_category: str | None = None
    suggestion_confidence: float | None = None
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "category": self.category,
            "confidence": self.confidence,
            "name": self.name,
            "company": self.company,
            "budget": self.budget,
            "intent": self.intent,
            "draft_reply": self.draft_reply,
            "model": self.model,
            "risk_flags": list(self.risk_flags),
            "secondary_categories": list(self.secondary_categories),
            "forwarded_by": self.forwarded_by,
            "contact_email": self.contact_email,
            "llm_error": self.llm_error,
            "model_suggestion": self.model_suggestion,
            "suggested_category": self.suggested_category,
            "suggestion_confidence": self.suggestion_confidence,
            "reasons": list(self.reasons),
        }


def _plain(email: dict) -> str:
    body = html_to_text(email.get("body") or "")
    return head_and_tail(f"{email.get('subject', '')}\n{body}")


def _score(text: str, email: dict, signals: dict | None = None) -> tuple[dict[str, float], list[str]]:
    scores = {name: 0.0 for name in ("lead", "support", "invoice", "spam", "urgent", "recruiter")}
    reasons: list[str] = []
    lowered = text.lower()
    sender = (email.get("from_email") or "").lower()

    def note(label: str) -> None:
        if label not in reasons:
            reasons.append(label)

    if re.search(r"\b(unsubscribe|opt out|manage preferences)\b", lowered):
        # A clear newsletter stays spam. The embedding head only fills a gap below 4.
        scores["spam"] += 5
        note("unsubscribe or opt-out")
    if re.search(r"\b(click below to claim|limited time offer|you(?:'ve| have) been selected)\b", lowered):
        scores["spam"] += 5
        note("promotional offer")
    if re.search(r"\b(lottery|inheritance|beneficiary|bitcoin giveaway|crypto wallet|viagra|guest post|backlinks?|do-?follow|work from home|seo package)\b", lowered):
        scores["spam"] += 5
        note("unsolicited promotion")
    if re.search(r"\b10x your\b", lowered):
        scores["spam"] += 4
    if _COLD.search(lowered):
        scores["spam"] += 6
        scores["lead"] -= 6

    if _invoice_evidence(lowered):
        scores["invoice"] += 5
        note("an amount due, an invoice number, or a payment request")
    if re.search(r"\b(we(?:'ve| have) wired|we have sent the payment|your receipt|payment received|receipt for)\b", lowered):
        scores["invoice"] += 4
        scores["lead"] -= 4
        scores["urgent"] -= 4
        note("a payment receipt")
    if _REFUND.search(lowered):
        scores["invoice"] += 6
        scores["lead"] -= 5

    outage = is_outage(lowered)
    impact = re.search(r"\b(every|all|nobody|customers?|patients?|orders|shoppers?)\b", lowered)
    harm = re.search(r"\b(throwing|returning|losing|can't|cannot|can not)\b", lowered)
    http_error = re.search(r"\b5\d\d\b", lowered)
    if outage:
        scores["urgent"] += 6
        note("a service is down")
    if http_error and impact and harm:
        scores["urgent"] += 6
    if re.search(r"\b(losing (?:orders|money|customers|patients))\b", lowered):
        scores["urgent"] += 4
    if re.search(
        r"\b(today before \d|today by \d|before \d{1,2}(?::\d{2})?\s?(?:am|pm)|by \d{1,2}\s?(?:am|pm) today|tonight|eod|by end of day|within the hour|in \d{1,2} hours?|within \d{1,2} hours?)\b",
        lowered,
    ):
        scores["urgent"] += 5
        note("a deadline is named")
    if re.search(r"\b(sev-?1|p0)\b", lowered):
        scores["urgent"] += 6
    immediacy = re.search(
        r"\b(right now|asap|immediately|caída|urgente|urgence)\b",
        lowered,
    )
    impact = re.search(
        r"\b(for everyone|everyone|every|nothing is shipping|blank (?:white )?page|errors on every|customers|orders|patients)\b",
        lowered,
    )
    broken = re.search(r"\b(down|broken|stopped|error|errors|failing|switch it off)\b", lowered)
    if re.search(r"\bnothing is shipping\b", lowered) or (
        re.search(r"\bblank (?:white )?page\b", lowered) and impact
    ):
        scores["urgent"] += 6
    if immediacy and (impact or broken):
        scores["urgent"] += 6
    if re.search(r"\b(caída|urgente)\b", lowered) and re.search(r"\b(caída|pedido|pedidos|web|página|pagina)\b", lowered):
        scores["urgent"] += 4

    if re.search(r"\b(proposal|pricing|rfp|retainer|freelancer|sow|demo|spend|could you quote|a quote)\b", lowered):
        scores["lead"] += 4
        note("asks for a proposal, quote, or retainer")
    if re.search(r"\b(hire|discovery call|set aside)\b", lowered):
        scores["lead"] += 3
    if re.search(r"\b(hourly|per hour|/hr|i can pay|we can pay)\b", lowered):
        scores["lead"] += 4
    if re.search(r"\b(budget|looking for|interested in a proposal|we'd like|we would like)\b", lowered):
        scores["lead"] += 2
    if extract_budget(lowered) and re.search(
        r"\b(want|looking|need|build|automat|hire|help us|help me)\b",
        lowered,
    ):
        scores["lead"] += 4
        note("a budget and a request")
    if re.search(r"\b(build (?:us |me )?|automatiz|見積)", lowered):
        scores["lead"] += 2
    if _COMMERCIAL.search(lowered) and extract_budget(lowered):
        scores["lead"] += 4
        note("a contract, scope, or budget")
    if _REFERRAL.search(lowered):
        scores["lead"] += 4
        note("a referral")

    if re.search(r"\b(not working|is broken|broken|bug|failing|failed|stopped firing|didn't arrive|did not arrive)\b", lowered):
        scores["support"] += 4
        note("a defect is described")
    if re.search(r"\berror\s?\d{3}\b", lowered) and not (http_error and impact and harm):
        scores["support"] += 4
    if re.search(r"\b(password reset|account locked|can't log ?in|cannot log ?in|won't download|blank screen)\b", lowered):
        scores["support"] += 4
    if re.search(r"\b(can you (?:check|look|take a look)|when you have a minute)\b", lowered):
        scores["support"] += 2
    if _SUPPORTISH.search(lowered):
        scores["support"] += 3
        if not _COMMERCIAL.search(lowered):
            scores["support"] = max(scores["support"], 5.0)
        note("a support question")
    if existing_thread(email) and _SUPPORTISH.search(lowered) and not _COMMERCIAL.search(lowered):
        scores["support"] += 4
        scores["lead"] -= 5
        note("a support thread")
    if _RECRUITER.search(lowered):
        scores["lead"] = 0
        scores["invoice"] = 0
        scores["recruiter"] = 6
        note("a recruiter")
    if _RENEWAL.search(lowered):
        scores["lead"] = 0
        if _invoice_evidence(lowered) or extract_budget(lowered):
            scores["invoice"] = max(scores["invoice"], 5)
            note("a renewal")
        else:
            scores["spam"] = max(scores["spam"], 5)
            note("an expiry notice")
    if _NOT_URGENT.search(lowered) or (_SUPPORTISH.search(lowered) and not is_outage(lowered)):
        scores["urgent"] = 0
        if _NOT_URGENT.search(lowered):
            note("the sender says it is not urgent")
    if scores["invoice"] > 0 and not _invoice_evidence(lowered) and scores["recruiter"] < 4:
        # A budget or a contract is not an invoice. Receipts and renewals already counted.
        if "a payment receipt" not in reasons and "a renewal" not in reasons:
            scores["invoice"] = 0

    if _VENDOR.search(lowered) or re.search(r"\b(no-?reply|noreply)\b", sender):
        scores["lead"] -= 8
        if scores["invoice"] < 4 and _VENDOR.search(lowered):
            scores["spam"] = max(scores["spam"], 5.0)
            note("an expiry notice")
        elif scores["invoice"] < 4:
            scores["spam"] += 3
    if _OOO.search(email.get("subject") or "") or _OOO.search(lowered):
        scores["lead"] -= 8
        scores["spam"] += 4
    auto = (email.get("auto_submitted") or "").lower()
    if auto and auto != "no":
        scores["lead"] -= 8
        scores["spam"] += 4

    if not (email.get("subject") or "").strip() and not html_to_text(email.get("body") or "").strip():
        scores["spam"] += 5
        scores["support"] -= 3
    # The embedding head fills a gap. A clear rule score is left alone.
    guessed = None
    signals = signals or {}
    if signals.get("negated", 0) >= 0.55 and not is_outage(lowered) and signals.get("outage", 0) < 0.7:
        scores["urgent"] = 0
        if signals.get("label") == "support" and not _NEWSLETTER.search(lowered):
            scores["spam"] = min(scores["spam"], 1.0)
            scores["support"] = max(scores["support"], 5.0)
        note("the sender says it is not urgent")
    if signals.get("outage", 0) >= 0.66 and signals.get("negated", 0) < 0.55 and scores["urgent"] < 4:
        scores["urgent"] = max(scores["urgent"], 6.0)
        note("customer impact")
    if max(scores.values()) < 4:
        guessed = signals.get("label")
        if (signals.get("label_p") or 0) < 0.45:
            guessed = None
        if guessed == "invoice" and not _invoice_evidence(lowered):
            guessed = None
        if guessed == "spam" and _COMMERCIAL.search(lowered):
            guessed = None
        if guessed in {"personal", "other"}:
            guessed = None
        if guessed == "lead" and (
            _RECRUITER.search(lowered)
            or (existing_thread(email) and _SUPPORTISH.search(lowered) and not _COMMERCIAL.search(lowered))
        ):
            guessed = None
        if guessed == "recruiter":
            scores["lead"] = 0
            scores["invoice"] = 0
            scores["recruiter"] = max(scores["recruiter"], 6.0)
        elif guessed in scores:
            scores[guessed] = max(scores[guessed], 5.0)
    if (
        _NEWSLETTER.search(lowered)
        and scores["support"] < 4
        and scores["urgent"] < 4
        and scores["invoice"] < 4
        and scores["lead"] < 6
    ):
        scores["lead"] = 0
        scores["spam"] = max(scores["spam"], 5.0)
        guessed = "spam"
        note("newsletter or unsubscribe")
    if guessed in scores and scores.get(guessed, 0) >= 5 and f"offline model: {guessed}" not in reasons:
        note(f"offline model: {guessed}")
    return scores, reasons[:4]


def _choose(scores: dict[str, float]) -> tuple[str, list[str], float, str | None, float]:
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_name, best = ranked[0]
    second = ranked[1][1]
    if best <= 0:
        return "review", [], 0.35, None, 0.0
    # A past-due invoice that only says "urgent" stays an invoice.
    if scores["invoice"] >= 4 and scores["invoice"] >= scores["urgent"] - 1 and best_name == "urgent":
        best_name, best = "invoice", scores["invoice"]
        second = max(value for name, value in scores.items() if name != "invoice")
    # Lead, invoice, and urgent are filed only when the score is clear.
    # Anything weaker waits in the review queue instead of being guessed.
    close = best < 5 and second >= 3 and best - second < 2
    margin = best - second
    decided = max(0.55, min(0.97, 0.62 + margin * 0.05))
    if best < 4 or (best_name in {"lead", "urgent", "invoice"} and close):
        suggestion = best_name if best >= 2 else None
        return "review", [], round(min(0.49, 0.28 + best * 0.04), 2), suggestion, round(decided, 2)
    secondary: list[str] = []
    if scores["lead"] >= 4 and scores["support"] >= 4 and best_name in {"lead", "support"}:
        other = "support" if best_name == "lead" else "lead"
        secondary.append(other)
    confidence = round(decided, 2)
    return best_name, secondary, confidence, best_name, confidence


def _name_tokens(value: str) -> list[str]:
    cleaned = value.replace(".", " ")
    tokens = [token for token in cleaned.split() if token.lower().strip(".") not in _HONORIFICS]
    return tokens


_PARTICLE = {
    "de",
    "van",
    "von",
    "da",
    "di",
    "du",
    "del",
    "der",
    "den",
    "ten",
    "ter",
    "la",
    "le",
    "el",
    "al",
    "bin",
    "st",
}


def is_person(value: str) -> bool:
    tokens = _name_tokens(value)
    if len(tokens) < 2 or len(tokens) > 4:
        return False
    capitals = 0
    for token in tokens:
        if token.lower() in _ROLE:
            return False
        letters = [char for char in token if char.isalpha()]
        if len(letters) < 2:
            return False
        if any(char.isdigit() for char in token):
            return False
        if not all(char.isalpha() or char in "-'’" for char in token):
            return False
        if token[0].isupper():
            capitals += 1
        elif token.lower() not in _PARTICLE:
            return False
    return capitals >= 2


def _display_name(value: str) -> str:
    return " ".join(_name_tokens(value))


# Last-word titles that are jobs even with a department in front ("Plant Manager").
# Counsel and partner are omitted: "Cho Counsel" is a firm, not a job.
_TITLE_LAST = _TITLE_TAIL - {"counsel", "partner"}


def is_title(line: str) -> bool:
    text = line.strip().rstrip(".")
    if _TITLE_PREFIX.search(text) or _JOB_LINE.match(text):
        return True
    words = re.findall(r"[^\W\d_]+", text, re.UNICODE)
    if not words or len(words) > 6:
        return False
    if len(words) <= 4 and words[-1].lower() in _TITLE_LAST:
        return True
    return all(word.lower() in _TITLE_WORD for word in words)


def _department(line: str) -> bool:
    """A mailbox or a desk, not the company that owns it."""
    words = re.findall(r"[^\W\d_]+", line, re.UNICODE)
    if not words:
        return False
    roleish = _ROLE | {"payable", "receivable", "desk"}
    if all(word.lower() in roleish for word in words):
        return True
    return len(words) <= 4 and words[-1].lower() in {"accounts", "desk", "team", "department"}


def _repeats_sender(line: str, sender: str) -> bool:
    """Skip a sign-off that only repeats the display name (Stripe under from: Stripe)."""

    def norm(value: str) -> str:
        words = [word.lower() for word in re.findall(r"[^\W\d_]+", value or "", re.UNICODE)]
        skip = {"inc", "llc", "ltd", "gmbh", "corp", "corporation", "limited"}
        return "".join(word for word in words if word not in skip)

    folded = norm(line)
    return bool(folded) and folded == norm(sender)


def _same_person(line: str, other: str) -> bool:
    if not is_person(line) or not is_person(other):
        return False
    return _display_name(line).casefold() == _display_name(other).casefold()


def _signature_lines(body: str) -> list[str]:
    lines = [line.strip() for line in html_to_text(body).splitlines()]
    for index, line in enumerate(lines):
        if _CLOSINGS.match(line):
            return [item for item in lines[index + 1 :] if item]
    tail = [line for line in lines if line][-4:]
    return tail


def _matches_mailbox(name: str, from_email: str) -> bool:
    local = re.sub(r"[^a-z]", "", (from_email or "").split("@", 1)[0].lower())
    parts = [re.sub(r"[^a-z]", "", part.lower()) for part in name.split()]
    parts = [part for part in parts if part]
    if len(parts) < 2 or not local:
        return False
    return parts[0] in local or parts[-1] in local


def extract_name(
    email: dict,
    known_contacts: list[dict] | None = None,
    accept_display: bool = False,
) -> str | None:
    """The CRM name is the From display name or the signature, never a greeting."""
    matched = _known_match(email, known_contacts)
    if matched and is_person(matched.get("name") or ""):
        return _display_name(matched["name"])
    signature = _signature_lines(email.get("body") or "")
    for line in signature:
        if is_title(line) or _department(line) or "。" in line or "、" in line or _GREETING.match(line):
            continue
        if is_person(line):
            display = _display_name(line)
            if _matches_mailbox(display, email.get("from_email") or "") or _same_person(line, email.get("from_name") or ""):
                return display
            break
        break
    candidate = (email.get("from_name") or "").strip()
    if _GREETING.match(candidate):
        return None
    if is_person(candidate) and (
        accept_display or _matches_mailbox(_display_name(candidate), email.get("from_email") or "")
    ):
        return _display_name(candidate)
    return None


def extract_company(email: dict, known_contacts: list[dict] | None = None) -> str | None:
    """Company from a known contact, an org line, or the signature. Never a greeting."""
    matched = _known_match(email, known_contacts)
    if matched and (matched.get("company") or "").strip():
        return str(matched["company"]).strip()
    org = re.search(
        r"(?m)^(?:company|organization|organisation|firma|société|公司)\s*:\s*(.+)$",
        email.get("body") or "",
        re.IGNORECASE,
    )
    if org:
        cleaned = _tidy_company(org.group(1).strip())
        if cleaned and not _GREETING.match(cleaned):
            return cleaned
    signature = _signature_lines(email.get("body") or "")
    seen_name = False
    sender = email.get("from_name") or ""
    address = email.get("from_email") or ""
    for line in signature:
        if "@" in line or line.lower().startswith("http"):
            continue
        if sum(character.isdigit() for character in line) >= 7:
            continue
        if is_title(line) or _department(line) or "。" in line or "、" in line or _GREETING.match(line):
            continue
        if line.endswith("،"):
            continue
        cleaned = _tidy_company(line)
        sender_name = (email.get("from_name") or "").strip()
        if sender_name and sender_name in cleaned and cleaned != sender_name:
            cleaned = _tidy_company(cleaned.replace(sender_name, " ")).strip(" ,.-")
            if not cleaned or re.fullmatch(
                r"(?i)(?:inc|llc|ltd|gmbh|corp|co|limited|incorporated)\.?",
                cleaned,
            ):
                continue
        if _HEADER_LINE.match(line):
            continue
        if _same_as_sender_name(cleaned, sender):
            seen_name = True
            continue
        if not seen_name and not is_person(cleaned) and _repeats_sender(cleaned, sender):
            continue
        if not _company_line(cleaned):
            continue
        if is_person(cleaned) and not seen_name:
            if _matches_mailbox(_display_name(cleaned), address) or _same_person(cleaned, sender):
                seen_name = True
                continue
        if not is_person(cleaned) or seen_name or not is_person(sender):
            return cleaned
    return None


def _tidy_company(line: str) -> str:
    text = line.strip()
    if _COMPANY_SUFFIX.search(text):
        return text
    return text.rstrip(".")


def _same_as_sender_name(line: str, sender: str) -> bool:
    """A first name, or the whole display name, is not the company."""
    def squash(value: str) -> str:
        return re.sub(r"\s+", "", (value or "").casefold())

    if squash(line) and squash(line) == squash(sender):
        return True
    words = [word.lower().strip(".") for word in line.split() if word.strip(".")]
    tokens = [word.lower().strip(".") for word in (sender or "").split() if word.strip(".")]
    if not words or not tokens:
        return False
    if " ".join(words) == " ".join(tokens):
        return True
    return len(words) == 1 and words[0] == tokens[0]


def _company_line(line: str) -> bool:
    if not line or len(line) > 60 or "?" in line or "!" in line or line.endswith(","):
        return False
    if line[0].islower():
        return False
    if re.match(r"^(hi|hey|hello|dear|this)\b", line, re.IGNORECASE):
        return False
    if re.search(r"[$€£¥]|amount due|\binvoice\b", line, re.IGNORECASE):
        return False
    if re.search(r"\b(is|are|was|were|please|click|unsubscribe|opt out|department|service)\b", line, re.IGNORECASE):
        return False
    if re.search(r"(様$|sort code|account\s*:|thanks for your)", line, re.IGNORECASE):
        return False
    if re.match(r"^(thanks|thank you)\b", line, re.IGNORECASE):
        return False
    return len(line.split()) <= 6


_GREETING = re.compile(
    r"^(?:hi|hey|hello|dear|hola|bonjour|hallo|ol[aá]|oi|merhaba|selam|salut|ciao|"
    r"hej|czesc|cześć|مرحبا|مرحباً|你好|こんにちは|안녕하세요)\b",
    re.IGNORECASE,
)
_TIMELINE = re.compile(
    r"\b(?:today|tomorrow|this week|next week|end of day|eod|net \d+|within \d+ (?:day|week|hour)s?|"
    r"by \d{1,2}(?::\d{2})?\s?(?:am|pm))\b",
    re.IGNORECASE,
)
_ASK_TOOLS = ("Python", "HubSpot", "Slack", "Shopify", "Zapier", "Gmail")


def summarize(text: str, limit: int = 110) -> str:
    """The first informative sentence, not a canned label."""
    kept: list[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or _GREETING.match(line) or _CLOSINGS.match(line) or _HEADER_LINE.match(line):
            continue
        if line.endswith(",") and len(line.split()) <= 4:
            continue
        kept.append(line)
    blob = re.sub(r"\s+", " ", " ".join(kept)).strip()
    sentence = re.split(r"(?<=[.!?])\s+", blob)[0] if blob else ""
    sentence = sentence.strip(" -")
    if len(sentence) > limit:
        clipped = sentence[: limit - 1].rsplit(" ", 1)[0]
        sentence = (clipped or sentence[: limit - 1]).rstrip(".,;:") + "…"
    return sentence


def _body_sentences(body: str) -> list[str]:
    kept: list[str] = []
    for line in (body or "").splitlines():
        line = line.strip()
        if not line or _GREETING.match(line) or _CLOSINGS.match(line) or _HEADER_LINE.match(line):
            continue
        if line.endswith(",") and len(line.split()) <= 4:
            continue
        kept.append(line)
    blob = re.sub(r"\s+", " ", " ".join(kept)).strip()
    if not blob:
        return []
    return [part.strip(" -") for part in re.split(r"(?<=[.!?])\s+", blob) if part.strip()]


def _company_from_domain(email: dict) -> str | None:
    """Use the sender's domain only when a person signed the note and no org line did."""
    body = email.get("body") or ""
    if not any(_CLOSINGS.match(line.strip()) for line in body.splitlines()):
        return None
    address = email.get("from_email") or ""
    if "@" not in address or free_mail(address):
        return None
    label = address.split("@", 1)[1].split(".")[0]
    letters = re.sub(r"[^A-Za-z]", "", label)
    if len(letters) < 4:
        return None
    return letters[:1].upper() + letters[1:]


def extract_intent(
    category: str,
    text: str,
    subject: str = "",
    budget: str | None = None,
    name: str | None = None,
    company: str | None = None,
) -> str:
    """A short template from the fields. No subject prefix and no body dump."""
    who = (company or "").strip()
    if not who and name and len(name.split()) >= 2:
        who = name.strip()
    if not who or len(who.split()) < 2 and not company:
        who = who if company else "Sender"
    if company:
        who = company.strip()
    low = text or ""
    if category == "suspicious":
        what = "Suspicious. Do not pay or reply"
    elif category == "recruiter":
        what = "Recruiter outreach"
    elif category == "spam":
        what = "Newsletter or promotion"
    elif category == "invoice":
        number = re.search(r"\b(?:invoice|inv)[^\d]{0,12}(\d{3,})", low, re.IGNORECASE)
        what = "Invoice"
        if number:
            what += f" {number.group(1)}"
        if re.search(r"\bpast due\b|\boverdue\b", low, re.IGNORECASE):
            what += ", past due"
        elif re.search(r"\breceipt\b|\bpayment received\b", low, re.IGNORECASE):
            what = "Receipt"
    elif category in {"urgent", "support"}:
        found = [
            token
            for token in ("broken", "form", "checkout", "booking", "login", "export", "error")
            if re.search(rf"\b{token}\b", low, re.IGNORECASE)
        ]
        what = "Reports " + " ".join(found[:3]) if found else (
            "Reports an outage" if category == "urgent" else "Asks for support"
        )
    else:
        if re.search(r"\bquote\b", low, re.IGNORECASE):
            what = "Wants a quote"
        elif re.search(r"\b(proposal|retainer|sow|statement of work|contract)\b", low, re.IGNORECASE):
            what = "Wants a proposal"
        else:
            what = "Wants help"
        tools = [tool for tool in _ASK_TOOLS if re.search(rf"\b{re.escape(tool)}\b", low, re.IGNORECASE)]
        if tools:
            what += " for " + " ".join(tools[:3])
    when = _TIMELINE.search(low)
    parts = [f"{who}: {what}"]
    if budget and budget.casefold() not in what.casefold():
        parts.append(budget)
    if when:
        parts.append(when.group(0))
    # The subject is not a field. It is never copied in.
    del subject
    line = "; ".join(part for part in parts if part)
    if len(line) > 140:
        line = line[:139].rstrip(" ,;:") + "…"
    return line


def draft_reply(
    category: str,
    name: str | None,
    intent: str,
    flags: list[str] | None = None,
    suggested: str | None = None,
    reasons: list[str] | None = None,
) -> str:
    if category == "suspicious":
        listed = ", ".join(flags or ["suspicious"])
        return f"No reply. Flagged as suspicious: {listed}."
    if category == "spam":
        return "No reply. This was filed as spam and will not be answered."
    if category == "recruiter":
        return "No reply. This is a recruiting note, not a client lead, and it is not written to the CRM."
    first = name.split()[0] if name else None
    hello = f"Hi {first}," if first else "Hi,"
    if category == "lead":
        focus = {
            "book a discovery call": "a short working session to see whether the workflow is a fit",
            "hire an automation freelancer": "a monthly automation engagement",
            "request a proposal": "a fixed-scope proposal",
        }.get(intent, "what you described")
        return (
            f"{hello}\n\n"
            f"Thanks for writing — I would like to help with {focus}. "
            "I can send two times this week, and a price, before any build starts.\n\n"
            "Asad"
        )
    if category == "invoice":
        return (
            f"{hello}\n\n"
            "This reads as billing, so I am leaving it with a person to check "
            "before anything is paid or marked closed.\n\n"
            "Asad"
        )
    if category == "review":
        hint = ""
        if suggested:
            why = ", ".join(reasons or [])
            hint = f" The closest label is {suggested}."
            if why:
                hint += f" What stood out: {why}."
        return (
            "I read this and I am not ready to file it."
            + hint
            + " Nothing goes to the CRM until someone accepts a label.\n\n"
            "Asad"
        )
    if category == "urgent":
        return (
            f"{hello}\n\n"
            "I have this at the top of the queue. "
            "You will get a status and the next step within the hour.\n\n"
            "Asad"
        )
    return (
        f"{hello}\n\n"
        "I have this logged. I will come back with the cause and the fix, "
        "or with the one detail I still need from you.\n\n"
        "Asad"
    )


def _suppress_budget(email: dict, text: str) -> bool:
    sender = (email.get("from_email") or "").lower()
    if re.search(r"\b(no-?reply|noreply)\b", sender):
        return True
    if _VENDOR.search(text) or _OOO.search(email.get("subject") or "") or _OOO.search(text):
        return True
    if _COLD.search(text):
        return True
    return False


def known_sender(email: dict, known_contacts: list[dict] | None) -> bool:
    sender = (email.get("from_email") or "").strip().lower()
    if not sender or not known_contacts:
        return False
    for contact in known_contacts:
        address = (contact.get("email") or "").strip().lower()
        if address and address == sender:
            return True
    return False


def existing_thread(email: dict) -> bool:
    """A reply, not a forward. Forwards are how a stranger arrives with a quote."""
    subject = email.get("subject") or ""
    if re.match(r"^\s*((re|aw|sv|antw)\s*:\s*)+", subject, re.IGNORECASE):
        return True
    if str(email.get("in_reply_to") or email.get("references") or "").strip():
        return True
    body = email.get("body") or ""
    if re.search(r"(?m)^>", body):
        return True
    if re.search(r"\nOn .{0,180} wrote:\s*\n", "\n" + body, re.IGNORECASE):
        return True
    return False


def _invoice_evidence(text: str) -> bool:
    """An amount due, an invoice number, a receipt, or a request to pay. A budget alone is not one."""
    if _INVOICE_EVIDENCE.search(text or "") or _REFUND.search(text or ""):
        return True
    if re.search(r"\b(?:payment of|payment will be charged|charged to (?:the |your )?card|amount\s*:)\b", text or "", re.IGNORECASE):
        return True
    if extract_budget(text or "") and re.search(
        r"\b(?:invoice|receipt|bill|rechnung|factura|fatura|請求書|发票)\b",
        text or "",
        re.IGNORECASE,
    ):
        return True
    return False


def is_outage(text: str) -> bool:
    """A service failure, not a same-day sales deadline or a single failed job.

    'Not working' counts when a system, site, checkout, or booking flow is the
    thing that failed. A single form or a login for one person stays support.
    """
    lowered = text or ""
    if _OUTAGE.search(lowered):
        return True
    if re.search(
        rf"\b(?:{_SERVICE})\b.{{0,48}}\b(?:{_DOWN_WORD})\b|\b(?:{_DOWN_WORD})\b.{{0,48}}\b(?:{_SERVICE})\b",
        lowered,
        re.IGNORECASE,
    ):
        return True
    if re.search(r"\b(?:emergency|emergencia)\b", lowered, re.IGNORECASE) and re.search(
        rf"\b(?:{_SERVICE}|offline|down|ca[ií]d[oa]|bookings)\b",
        lowered,
        re.IGNORECASE,
    ):
        return True
    # A price like $4,500 is not an HTTP 500. The status has to stand alone.
    if re.search(r"(?<![\d,.])\b5\d\d\b(?![\d,.])", lowered) and re.search(
        r"\b(customers?|orders?|patients?|checkout|shoppers?)\b",
        lowered,
        re.IGNORECASE,
    ):
        return True
    return bool(re.search(r"\b(losing (?:orders|money|customers|patients))\b", lowered, re.IGNORECASE))


def has_operational_pressure(text: str) -> bool:
    """An outage or a deadline. Immediacy alone is not pressure."""
    lowered = (text or "").lower()
    if is_outage(lowered) or re.search(
        r"\b(went down|is down|are down|production is down|outage|offline|not responding)\b",
        lowered,
    ):
        return True
    if re.search(
        r"\b(today before \d|today by \d|before \d{1,2}(?::\d{2})?\s?(?:am|pm)|by \d{1,2}\s?(?:am|pm) today|tonight|eod|by end of day|within the hour|in \d{1,2} hours?|within \d{1,2} hours?)\b",
        lowered,
    ):
        return True
    if re.search(r"\b(sev-?1|p0)\b", lowered):
        return True
    if re.search(r"\b(losing (?:orders|money|customers|patients)|nothing is shipping)\b", lowered):
        return True
    if re.search(r"\b(caída|urgente)\b", lowered) and re.search(r"\b(caída|pedido|pedidos|web|página|pagina)\b", lowered):
        return True
    immediacy = re.search(r"\b(right now|asap|immediately|caída|urgente|urgence)\b", lowered)
    impact = re.search(
        r"\b(for everyone|everyone|every|nothing is shipping|blank (?:white )?page|errors on every|customers|orders|patients)\b",
        lowered,
    )
    broken = re.search(r"\b(down|broken|stopped|error|errors|failing|switch it off)\b", lowered)
    if re.search(r"\b5\d\d\b", lowered) and impact and re.search(r"\b(throwing|returning|losing|can't|cannot|can not)\b", lowered):
        return True
    return bool(immediacy and (impact or broken))


def urgent_allowed(
    email: dict,
    text: str,
    known_contacts: list[dict] | None,
    outage_signal: bool = False,
) -> bool:
    """A real outage is urgent from a stranger or from a known contact.

    A deadline with no outage still needs a known sender or a thread. Payment
    mail, a calendar invite, and an image with no readable body stay out.
    ``outage_signal`` is the urgency head, so a paraphrase the keyword list
    misses still counts.
    """
    if (payment_related(text) or "payment_related" in (email.get("risk_flags") or [])) and not outage_signal:
        return False
    raw = email.get("body") or ""
    if re.search(r"BEGIN:VCALENDAR|text/calendar|METHOD:REQUEST", raw, re.IGNORECASE):
        return False
    outage = outage_signal or is_outage(text)
    if not has_operational_pressure(text) and not outage:
        return False
    if known_sender(email, known_contacts) or existing_thread(email):
        return True
    if len(html_to_text(raw).strip()) < 40:
        return False
    return outage


def _neighbor_lookalike(email: dict, text: str, contacts: list[dict] | None) -> bool:
    """A one-edit domain of someone in this mailbox, and a request to move money."""
    if not contacts:
        return False
    if not re.search(r"\b(?:wire|transfer|bank account|payout)\b", text or "", re.IGNORECASE):
        return False
    sender = (email.get("from_email") or "").split("@")[-1]
    return known_contact_lookalike(sender, contacts)


def _known_match(email: dict, known_contacts: list[dict] | None) -> dict | None:
    sender = (email.get("from_email") or "").strip().lower()
    if not sender:
        return None
    for contact in known_contacts or []:
        if (contact.get("email") or "").strip().lower() == sender:
            return contact
    return None


def classify_rules(email: dict, known_contacts: list[dict] | None = None, domain_contacts: list[dict] | None = None) -> Classification:
    prepared = unwrap_forward(email)
    raw = prepared.get("body") or ""
    full = _plain(prepared)
    text = strip_quotes(strip_injection_notes(full))
    signals = assess(text)
    flags = assess_risk(prepared, full, raw, known_contacts)
    if "lookalike_domain" not in flags and _neighbor_lookalike(prepared, full, domain_contacts):
        flags.append("lookalike_domain")
    contacts = [*(known_contacts or []), *(domain_contacts or [])]
    if decide_suspicious(prepared, full, contacts, signals.get("money_sim") or 0.0):
        if "risk_score" not in flags:
            flags.append("risk_score")
    blocking = hard_flags(flags)
    visible = dict(prepared)
    visible["body"] = strip_quotes(html_to_text(raw))
    if blocking:
        category, secondary = settle("suspicious", [], True)
        return Classification(
            category=category,
            confidence=0.9,
            name=extract_name(visible, known_contacts),
            company=extract_company(visible, known_contacts),
            budget=None,
            intent="Suspicious. Do not pay or reply.",
            draft_reply=draft_reply("suspicious", None, "", blocking),
            model="rules",
            risk_flags=flags,
            secondary_categories=secondary,
            forwarded_by=prepared.get("forwarded_by"),
            contact_email=prepared.get("from_email"),
        )
    scores, reasons = _score(text, prepared, signals)
    category, secondary, confidence, suggested, suggestion_confidence = _choose(scores)
    name = extract_name(visible, known_contacts, accept_display=category not in {"spam", "suspicious"})
    company = extract_company(visible, known_contacts)
    if company is None and category not in {"spam", "suspicious"}:
        company = _company_from_domain(visible)
    auto = (prepared.get("auto_submitted") or "").lower()
    if _OOO.search(prepared.get("subject") or "") or _OOO.search(text) or (auto and auto != "no"):
        name = None
        company = None
    body_only = strip_quotes(strip_injection_notes(html_to_text(prepared.get("body") or "")))
    budget = extract_budget(text)
    if budget and (category == "recruiter" or _SALARY.search(text) or _RECRUITER.search(text)):
        budget = None
    if budget and category == "review" and "a price is written in the message" not in reasons:
        reasons = [*reasons, "a price is written in the message"]
    if budget and _suppress_budget(prepared, text) and category not in {"invoice", "lead"}:
        budget = None
    intent = extract_intent(category, body_only, prepared.get("subject") or "", budget, name, company)
    concealed = hidden_text(raw)
    readable = f"{prepared.get('subject') or ''}\n{text}\n{concealed}"
    # Payment mail is not filed and is not urgent. The person verifies it by phone.
    if payment_related(readable) and category in {"lead", "urgent"}:
        suggested = suggested or category
        if "payment-related: verify by phone" not in reasons:
            reasons.append("payment-related: verify by phone")
        if "payment_related" not in flags:
            flags = [*flags, "payment_related"]
        category = "review"
        confidence = min(confidence, 0.45)
    # A first contact that only sounds urgent stays in review, including phishing-looking mail.
    outage_signal = (signals.get("outage") or 0) >= 0.66 and (signals.get("negated") or 0) < 0.55
    if category == "urgent" and not urgent_allowed(prepared, readable, known_contacts, outage_signal):
        suggested = suggested or "urgent"
        if "urgent needs a known sender or an existing thread" not in reasons:
            reasons.append("urgent needs a known sender or an existing thread")
        category = "review"
        confidence = min(confidence, 0.45)
    elif category == "urgent" and not known_sender(prepared, known_contacts) and not existing_thread(prepared):
        if "unverified sender" not in reasons:
            reasons.append("unverified sender")
    if category != "suspicious" and (category == "invoice" or suggested == "invoice") and _OVERDUE.search(readable):
        if "urgent" not in secondary:
            secondary = [*secondary, "urgent"]
        if "overdue invoice" not in reasons:
            reasons.append("overdue invoice")
    category, secondary = settle(category, secondary, bool(blocking))
    return Classification(
        category=category,
        confidence=confidence,
        name=name,
        company=company,
        budget=budget,
        intent=intent,
        draft_reply=draft_reply(category, name, intent, suggested=suggested, reasons=reasons),
        model="rules",
        risk_flags=flags,
        secondary_categories=secondary,
        forwarded_by=prepared.get("forwarded_by"),
        contact_email=prepared.get("from_email"),
        suggested_category=suggested,
        suggestion_confidence=suggestion_confidence,
        reasons=reasons,
    )


def classification_from_payload(payload: dict, model: str) -> Classification:
    """Validate an object. Non-objects and unknown categories raise ValueError."""
    if not isinstance(payload, dict):
        raise ValueError("Model JSON was not an object")
    category = payload.get("category")
    if not isinstance(category, str):
        raise ValueError("category must be a string")
    category = category.strip().lower()
    if category not in CATEGORIES:
        raise ValueError(f"Unknown category: {category!r}")
    try:
        confidence = float(payload.get("confidence", 0.5))
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be a number") from exc
    if not 0 <= confidence <= 1:
        raise ValueError("confidence out of range")

    def clean(value: object, limit: int) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("field must be a string or null")
        text = value.strip()
        if not text:
            return None
        if len(text) > limit:
            raise ValueError("field is too long")
        return text

    name = clean(payload.get("name"), 120)
    company = clean(payload.get("company"), 160)
    raw_budget = clean(payload.get("budget"), 80)
    budget = extract_budget(raw_budget) if raw_budget else None
    if raw_budget and budget is None:
        budget = raw_budget
    intent = clean(payload.get("intent"), 80) or "review the message"
    reply = clean(payload.get("draft_reply"), 2000) or draft_reply(category, name, intent)
    if re.search(r"\b(i have sent|i've sent|already booked|i have already)\b", reply, re.IGNORECASE):
        raise ValueError("draft claims an action was already taken")
    return Classification(
        category=category,
        confidence=round(confidence, 2),
        name=name,
        company=company,
        budget=budget,
        intent=intent,
        draft_reply=reply,
        model=model,
    )
