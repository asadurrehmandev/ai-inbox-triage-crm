"""Rule engine used when no model key is set, and as the visible fallback.

Patterns are general (outages, invoices, proposals, promotions). They are not
a word list copied from the sample mailbox. Phishing and injection are decided
in app.risk before any category score is trusted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.budget import extract_budget
from app.prepare import head_and_tail, hidden_text, html_to_text, strip_injection_notes, strip_quotes, unwrap_forward
from app.risk import assess_risk, hard_flags, payment_related

CATEGORIES = ("lead", "support", "invoice", "spam", "urgent", "suspicious", "review")

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
    r"^(out of office|automatic reply|auto-?reply)\b|i am out of the office",
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


def _score(text: str, email: dict) -> tuple[dict[str, float], list[str]]:
    scores = {name: 0.0 for name in ("lead", "support", "invoice", "spam", "urgent")}
    reasons: list[str] = []
    lowered = text.lower()
    sender = (email.get("from_email") or "").lower()

    def note(label: str) -> None:
        if label not in reasons:
            reasons.append(label)

    if re.search(r"\b(unsubscribe|opt out|manage preferences)\b", lowered):
        scores["spam"] += 3
        note("unsubscribe or opt-out")
    if re.search(r"\b(click below to claim|limited time offer|you(?:'ve| have) been selected)\b", lowered):
        scores["spam"] += 5
        note("promotional offer")
    if re.search(r"\b(lottery|inheritance|beneficiary|bitcoin giveaway|crypto wallet|viagra|guest post|work from home|seo package)\b", lowered):
        scores["spam"] += 5
        note("unsolicited promotion")
    if re.search(r"\b10x your\b", lowered):
        scores["spam"] += 4
    if _COLD.search(lowered):
        scores["spam"] += 6
        scores["lead"] -= 6

    if re.search(r"\b(invoice|rechnung|amount due|past due|payment due|net\s?\d+|remittance|payment received)\b", lowered):
        scores["invoice"] += 4
        note("billing language")
    if re.search(r"\binv-\d+\b", lowered):
        scores["invoice"] += 3
        note("invoice number")
    if re.search(r"\b(we(?:'ve| have) wired|we have sent the payment|your receipt|payment of)\b", lowered):
        scores["invoice"] += 4
        note("a payment receipt")
    if _REFUND.search(lowered):
        scores["invoice"] += 6
        scores["lead"] -= 5

    outage = re.search(r"\b(went down|is down|are down|production is down|outage|offline|not responding)\b", lowered)
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
    if re.search(r"\b(build (?:us |me )?|automatiz|見積)", lowered):
        scores["lead"] += 2

    if re.search(r"\b(not working|is broken|broken|bug|failing|failed|stopped firing|didn't arrive|did not arrive)\b", lowered):
        scores["support"] += 4
        note("a defect is described")
    if re.search(r"\berror\s?\d{3}\b", lowered) and not (http_error and impact and harm):
        scores["support"] += 4
    if re.search(r"\b(password reset|account locked|can't log ?in|cannot log ?in|won't download|blank screen)\b", lowered):
        scores["support"] += 4
    if re.search(r"\b(can you (?:check|look|take a look)|when you have a minute)\b", lowered):
        scores["support"] += 2

    if _VENDOR.search(lowered) or re.search(r"\b(no-?reply|noreply)\b", sender):
        scores["lead"] -= 8
        if scores["invoice"] < 4:
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


def is_person(value: str) -> bool:
    tokens = _name_tokens(value)
    if len(tokens) < 2 or len(tokens) > 4:
        return False
    for token in tokens:
        if token.lower() in _ROLE:
            return False
        letters = [char for char in token if char.isalpha()]
        if len(letters) < 2 or not token[0].isupper():
            return False
        if any(char.isdigit() for char in token):
            return False
        if not all(char.isalpha() or char in "-'’" for char in token):
            return False
    return True


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


def extract_name(email: dict) -> str | None:
    signature = _signature_lines(email.get("body") or "")
    for line in signature:
        if is_title(line) or _department(line) or "。" in line or "、" in line:
            continue
        if is_person(line):
            display = _display_name(line)
            if _matches_mailbox(display, email.get("from_email") or "") or _same_person(line, email.get("from_name") or ""):
                return display
            break
        break
    candidate = (email.get("from_name") or "").strip()
    if is_person(candidate) and _matches_mailbox(_display_name(candidate), email.get("from_email") or ""):
        return _display_name(candidate)
    return None


def extract_company(email: dict) -> str | None:
    signature = _signature_lines(email.get("body") or "")
    seen_name = False
    sender = email.get("from_name") or ""
    address = email.get("from_email") or ""
    for line in signature:
        if "@" in line or line.lower().startswith("http"):
            continue
        if sum(character.isdigit() for character in line) >= 7:
            continue
        if is_title(line) or _department(line) or "。" in line or "、" in line:
            continue
        cleaned = line.strip().rstrip(".")
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


def _company_line(line: str) -> bool:
    if not line or len(line) > 60 or "?" in line or "!" in line or line.endswith(","):
        return False
    if line[0].islower():
        return False
    if re.match(r"^(hi|hey|hello|dear|this)\b", line, re.IGNORECASE):
        return False
    if re.search(r"\b(is|are|was|were|please|click|unsubscribe|opt out|department|service)\b", line, re.IGNORECASE):
        return False
    if re.search(r"(様$|sort code|account\s*:|thanks for your)", line, re.IGNORECASE):
        return False
    if re.match(r"^(thanks|thank you)\b", line, re.IGNORECASE):
        return False
    return len(line.split()) <= 6


def extract_intent(category: str, text: str) -> str:
    if category == "review":
        return "needs a person to read it"
    if category == "suspicious":
        return "review a suspicious message"
    if category == "spam":
        return "unsolicited promotion"
    if category == "urgent":
        if re.search(r"\b(down|outage|sev-?1|p0|5\d\d)\b", text, re.IGNORECASE):
            return "escalate an outage"
        return "meet a same-day deadline"
    if category == "invoice":
        if re.search(r"\b(remittance|payment received)\b", text, re.IGNORECASE):
            return "confirm remittance"
        if _REFUND.search(text):
            return "resolve a duplicate charge"
        return "collect a payment"
    if category == "support":
        if re.search(r"\b(password reset|account locked|can't log)\b", text, re.IGNORECASE):
            return "restore account access"
        return "resolve a product issue"
    if re.search(r"\b(discovery call|demo|meeting)\b", text, re.IGNORECASE):
        return "book a discovery call"
    if re.search(r"\b(retainer|freelancer|hire)\b", text, re.IGNORECASE):
        return "hire an automation freelancer"
    return "request a proposal"


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


def has_operational_pressure(text: str) -> bool:
    """An outage or a deadline. Immediacy alone is not pressure."""
    lowered = (text or "").lower()
    if re.search(r"\b(went down|is down|are down|production is down|outage|offline|not responding)\b", lowered):
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


def urgent_allowed(email: dict, text: str, known_contacts: list[dict] | None) -> bool:
    """Urgent requires a known sender or a real thread, plus an outage or a deadline.

    Payment mail and anything the caller has already decided is uncertain stay out.
    """
    if payment_related(text) or "payment_related" in (email.get("risk_flags") or []):
        return False
    if not has_operational_pressure(text):
        return False
    return known_sender(email, known_contacts) or existing_thread(email)


def classify_rules(email: dict, known_contacts: list[dict] | None = None) -> Classification:
    prepared = unwrap_forward(email)
    raw = prepared.get("body") or ""
    full = _plain(prepared)
    text = strip_quotes(strip_injection_notes(full))
    flags = assess_risk(prepared, full, raw, known_contacts)
    blocking = hard_flags(flags)
    visible = dict(prepared)
    visible["body"] = strip_quotes(html_to_text(raw))
    if blocking:
        return Classification(
            category="suspicious",
            confidence=0.9,
            name=extract_name(visible),
            company=extract_company(visible),
            budget=None,
            intent="review a suspicious message",
            draft_reply=draft_reply("suspicious", None, "", blocking),
            model="rules",
            risk_flags=flags,
            forwarded_by=prepared.get("forwarded_by"),
            contact_email=prepared.get("from_email"),
        )
    scores, reasons = _score(text, prepared)
    category, secondary, confidence, suggested, suggestion_confidence = _choose(scores)
    name = extract_name(visible)
    company = extract_company(visible)
    auto = (prepared.get("auto_submitted") or "").lower()
    if _OOO.search(prepared.get("subject") or "") or _OOO.search(text) or (auto and auto != "no"):
        name = None
        company = None
    budget = extract_budget(text)
    if budget and category == "review" and "a price is written in the message" not in reasons:
        reasons = [*reasons, "a price is written in the message"]
    if budget and _suppress_budget(prepared, text) and category not in {"invoice", "lead"}:
        budget = None
    intent = extract_intent(category, text)
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
    if category == "urgent" and not urgent_allowed(prepared, readable, known_contacts):
        suggested = suggested or "urgent"
        if "urgent needs a known sender or an existing thread" not in reasons:
            reasons.append("urgent needs a known sender or an existing thread")
        category = "review"
        confidence = min(confidence, 0.45)
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
