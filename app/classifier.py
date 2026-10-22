"""Classify a business email and pull out the fields a CRM needs.

The rule engine is the demo path: it runs with no API key. When
ANTHROPIC_API_KEY or OPENAI_API_KEY is set, classify_email() asks that
model and falls back here if the call fails.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

CATEGORIES = ("lead", "support", "invoice", "spam", "urgent")

# Earlier entries win when two categories land on the same score.
PRIORITY = ("urgent", "invoice", "spam", "lead", "support")

PATTERNS: dict[str, list[tuple[str, float]]] = {
    "spam": [
        (r"\bunsubscribe\b", 2),
        (r"\b(viagra|cialis|pharmacy)\b", 6),
        (r"\b(airdrop|bitcoin giveaway|crypto wallet)\b", 6),
        (r"\byou(?:'ve| have) been selected\b", 5),
        (r"\b(lottery|inheritance|beneficiary)\b", 6),
        (r"\bdear business owner\b", 5),
        (r"\bguest post\b", 5),
        (r"\bwork from home\b", 5),
        (r"\b(10x your|rank on google|seo package)\b", 4),
        (r"\bclick below to claim\b", 5),
        (r"\blimited time offer\b", 3),
    ],
    "invoice": [
        (r"\binvoice\b", 4),
        (r"\binv-\d+\b", 3),
        (r"\b(past due|amount due|payment due|net\s?\d+)\b", 4),
        (r"\bremittance\b", 5),
        (r"\bbilling statement\b", 5),
        (r"\bpayment received\b", 3),
    ],
    "urgent": [
        (r"\b(production (is )?down|system is down|servers? (is|are) down)\b", 6),
        (r"\boutage\b", 5),
        (r"\b(sev-?1|p0)\b", 6),
        (r"\b(by end of day|within the hour|in \d+ hours?)\b", 4),
        (r"\basap\b", 2),
        (r"\burgent\b", 1.5),
    ],
    "lead": [
        (r"\b(proposal|quote|pricing|rfp)\b", 4),
        (r"\b(discovery call|demo|kickoff)\b", 3),
        (r"\b(retainer|freelancer)\b", 4),
        (r"\bhire\b", 3),
        (r"\b(budget|per month|/mo)\b", 2),
        (r"\b(gohighlevel|hubspot)\b", 1.5),
        (r"\b(interested in|looking for)\b", 2),
    ],
    "support": [
        (r"\b(can'?t|cannot) (log|sign) ?in\b", 5),
        (r"\b(password reset|account locked|error\s*\d{3})\b", 4),
        (r"\b(not working|is broken|bug|failing|failed|stopped firing)\b", 4),
        (r"\b(won'?t download|blank screen)\b", 4),
        (r"\b(help|how do i)\b", 2),
        (r"\b(ticket|webhook)\b", 1.5),
    ],
}

CLOSINGS = re.compile(
    r"^(thanks|thank you|best|regards|kind regards|sincerely|cheers|warmly),?\s*$",
    re.IGNORECASE,
)

NOT_A_PERSON = {
    "accounts",
    "payable",
    "team",
    "support",
    "newsletter",
    "billing",
    "ops",
    "admin",
    "rewards",
    "desk",
    "notification",
    "notifications",
    "info",
    "sales",
    "marketing",
    "noreply",
    "office",
    "bot",
    "mailer",
    "rankings",
    "offers",
    "prize",
    "center",
    "claims",
    "promo",
    "system",
    "notice",
    "security",
    "income",
    "home",
    "atlas",
    "growth",
    "editorial",
    "health",
    "ap",
}

TITLE_WORDS = {
    "director",
    "manager",
    "officer",
    "counsel",
    "engineer",
    "coordinator",
    "founder",
    "consultant",
    "owner",
    "president",
    "specialist",
    "administrator",
    "attorney",
    "partner",
    "producer",
    "controller",
    "accountant",
    "bookkeeper",
    "designer",
    "architect",
    "principal",
    "associate",
    "senior",
    "junior",
    "head",
    "vice",
    "general",
    "assistant",
    "chief",
    "of",
    "the",
    "and",
    "operations",
    "plant",
    "office",
    "systems",
    "it",
    "accounts",
    "account",
}

MONEY = re.compile(
    r"(?P<cur>USD|US\$|\$|€|£)\s?(?P<num>\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2})?",
    re.IGNORECASE,
)
SHORTHAND = re.compile(r"(?<![A-Za-z])(\d+(?:\.\d+)?)\s*k\b", re.IGNORECASE)


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

    def as_dict(self) -> dict:
        return asdict(self)


def message_text(email: dict) -> str:
    return f"{email.get('subject', '')}\n{email.get('body', '')}"


def score_categories(text: str) -> dict[str, float]:
    scores = {category: 0.0 for category in CATEGORIES}
    for category, rules in PATTERNS.items():
        for pattern, weight in rules:
            if re.search(pattern, text, re.IGNORECASE):
                scores[category] += weight
    return scores


def choose_category(scores: dict[str, float]) -> tuple[str, float]:
    best = max(scores.values())
    if best <= 0:
        return "support", 0.41
    category = next(name for name in PRIORITY if scores[name] == best)
    ordered = sorted(scores.values(), reverse=True)
    margin = ordered[0] - ordered[1]
    confidence = max(0.55, min(0.97, 0.64 + margin * 0.06))
    return category, round(confidence, 2)


def signature_lines(body: str) -> list[str]:
    lines = [line.strip() for line in body.splitlines()]
    for index, line in enumerate(lines):
        if CLOSINGS.match(line):
            return [item for item in lines[index + 1 :] if item]
    return []


def is_person(value: str) -> bool:
    parts = value.split()
    if len(parts) < 2 or len(parts) > 3:
        return False
    for part in parts:
        if not re.fullmatch(r"[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?", part):
            return False
        if part.lower() in NOT_A_PERSON:
            return False
    return True


def is_title(line: str) -> bool:
    words = re.findall(r"[A-Za-z&]+", line)
    if not words or len(words) > 4:
        return False
    return all(word.lower() in TITLE_WORDS for word in words)


def matches_mailbox(name: str, from_email: str) -> bool:
    local = re.sub(r"[^a-z]", "", from_email.split("@", 1)[0].lower())
    parts = [re.sub(r"[^a-z]", "", part.lower()) for part in name.split()]
    parts = [part for part in parts if part]
    return len(parts) >= 2 and parts[0] in local and parts[-1] in local


def extract_name(email: dict) -> str | None:
    signature = signature_lines(email.get("body") or "")
    if signature:
        if is_person(signature[0]):
            return signature[0]
        return None
    candidate = (email.get("from_name") or "").strip()
    if is_person(candidate) and matches_mailbox(candidate, email.get("from_email") or ""):
        return candidate
    return None


def extract_company(email: dict) -> str | None:
    signature = signature_lines(email.get("body") or "")
    for line in signature[1:]:
        if "@" in line or line.lower().startswith("http"):
            continue
        digits = sum(character.isdigit() for character in line)
        if digits >= 7:
            continue
        # Company names often look like personal names (Brightline Dental).
        # The person, when there is one, is the first signature line.
        if is_title(line):
            continue
        cleaned = line.strip().rstrip(".")
        if cleaned:
            return cleaned
    return None


def extract_budget(text: str) -> str | None:
    match = MONEY.search(text)
    if match:
        symbol = match.group("cur").upper()
        if symbol in {"USD", "US$"}:
            symbol = "$"
        elif symbol == "$":
            symbol = "$"
        amount = int(match.group("num").replace(",", ""))
        return f"{symbol}{amount:,}"
    shorthand = SHORTHAND.search(text)
    if shorthand:
        amount = int(float(shorthand.group(1)) * 1000)
        return f"${amount:,}"
    return None


def extract_intent(category: str, text: str) -> str:
    if category == "spam":
        return "unsolicited promotion"
    if category == "urgent":
        if re.search(r"\b(down|outage|sev-?1|p0)\b", text, re.IGNORECASE):
            return "escalate an outage"
        return "meet a same-day deadline"
    if category == "invoice":
        if re.search(r"\b(remittance|payment received|amount paid)\b", text, re.IGNORECASE):
            return "confirm remittance"
        return "collect a payment"
    if category == "support":
        if re.search(
            r"\b(can'?t|cannot) (log|sign) ?in\b|\bpassword reset\b|\baccount locked\b",
            text,
            re.IGNORECASE,
        ):
            return "restore account access"
        return "resolve a product issue"
    if re.search(r"\b(discovery call|demo|meeting)\b", text, re.IGNORECASE):
        return "book a discovery call"
    if re.search(r"\b(retainer|freelancer|hire)\b", text, re.IGNORECASE):
        return "hire an automation freelancer"
    return "request a proposal"


def draft_reply(category: str, name: str | None, intent: str) -> str:
    if category == "spam":
        return "No reply. This was filed as spam and will not be answered."
    first = name.split()[0] if name else None
    hello = f"Hi {first}," if first else "Hi,"
    if category == "lead":
        focus = {
            "book a discovery call": "a short working session to see whether the workflow is a fit",
            "hire an automation freelancer": "a monthly automation engagement",
            "request a proposal": "a fixed-scope proposal",
        }.get(intent, "the workflow you described")
        return (
            f"{hello}\n\n"
            f"Thanks for writing. I can help with {focus}. "
            "I will send two times this week and a clear price before any build starts.\n\n"
            "Asad Rehman\nLane"
        )
    if category == "invoice":
        if intent == "confirm remittance":
            action = "I will match this against the open item and confirm it is closed today."
        else:
            action = "I will match this against the open invoice and confirm payment status today."
        return f"{hello}\n\nReceived. {action}\n\nAsad Rehman\nLane"
    if category == "urgent":
        return (
            f"{hello}\n\n"
            "I have this and I am treating it as urgent. "
            "You will get a status and the next concrete step within the hour.\n\n"
            "Asad Rehman\nLane"
        )
    return (
        f"{hello}\n\n"
        "I have this logged. I will reply with the cause and the fix, "
        "or with the one detail I still need from you.\n\n"
        "Asad Rehman\nLane"
    )


def classify_rules(email: dict) -> Classification:
    text = message_text(email)
    category, confidence = choose_category(score_categories(text))
    name = extract_name(email)
    company = extract_company(email)
    budget = extract_budget(text)
    intent = extract_intent(category, text)
    return Classification(
        category=category,
        confidence=confidence,
        name=name,
        company=company,
        budget=budget,
        intent=intent,
        draft_reply=draft_reply(category, name, intent),
        model="rules",
    )


def classification_from_payload(payload: dict, model: str) -> Classification:
    category = str(payload.get("category", "")).strip().lower()
    if category not in CATEGORIES:
        raise ValueError(f"Unknown category: {category!r}")
    try:
        confidence = float(payload.get("confidence", 0.5))
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be a number") from exc
    confidence = max(0.0, min(1.0, confidence))

    def clean(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    name = clean(payload.get("name"))
    intent = clean(payload.get("intent")) or "review the message"
    reply = clean(payload.get("draft_reply")) or draft_reply(category, name, intent)
    return Classification(
        category=category,
        confidence=round(confidence, 2),
        name=name,
        company=clean(payload.get("company")),
        budget=clean(payload.get("budget")),
        intent=intent,
        draft_reply=reply,
        model=model,
    )
