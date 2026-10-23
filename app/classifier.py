"""Rule engine used when no model key is set, and as the visible fallback.

Category scores are regular expressions: invoices, proposals, recruiting,
opt-out, receipts, and lottery or token spam. The embedding head fills a label
only when those scores stay under 4. Urgency is a separate head. A same-day
legal or operational deadline is a closed class on top of that head. Phishing
and injection are decided in app.risk before any category score is trusted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.budget import extract_budget
from app.heads import assess, negation_threshold, urgency_threshold
from app.prepare import head_and_tail, hidden_text, html_to_text, strip_injection_notes, strip_quotes, unwrap_forward
from app.rank import settle
from app.risk import assess_risk, free_mail, hard_flags, known_contact_lookalike, payment_related
from app.risk_score import decide_suspicious

CATEGORIES = ("lead", "support", "invoice", "spam", "urgent", "suspicious", "review", "recruiter")

_CLOSINGS = re.compile(
    r"^(thanks|thank you|best regards|kind regards|warm regards|many thanks|best|regards|sincerely|cheers|warmly|"
    r"cordialement|saludos|gracias|merci|obrigad[oa]|danke|mit freundlichen grüßen),?\s*$",
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
_INVOICE_EVIDENCE = re.compile(
    r"\b(?:amount due|balance due|payment due|total due|please pay|kindly pay|"
    r"pay this invoice|invoice\s*#?\s*\d+|inv-\d+|past due|remittance|"
    r"payment received|your receipt|receipt for|order receipt|trip receipt|"
    r"importe pendiente|montant d[uû]|offene(?:r|n)? betrag|valor em aberto|"
    r"应付|請求書|お支払額)\b"
    r"|factura\s*(?:n[oº.]|no|#|\d)"
    r"|rechnung\s*(?:nr|#|\d)"
    r"|fatura\s*(?:n|#|\d)"
    r"|\b(?:recibo(?:\s+de(?:l| su)?(?:\s+pedido)?)?|reçu|quittung|nota fiscal)\b",
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
    r"\b(?:salary|compensation|\bote\b|per annum|annually|base pay|salario|gehalt|salaire)\b",
    re.IGNORECASE,
)
_SALARY_PERIOD = re.compile(
    r"\b(?:a year|per year|per annum|annually|al año|par an|pro jahr|por ano)\b",
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
    r"no funciona|ne fonctionne pas|funktioniert nicht)\b",
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
    r"(?:unsubscribe|opt[- ]out|manage preferences|newsletter|webinar|"
    r"abbestellen|abmelden|désabonner|desabonner|darse de baja|descadastrar|"
    r"إلغاء الاشتراك|退订|取消订阅|配信停止|"
    r"tir(?:é|e) au sort|allocation de jetons|loter[ií]a|ha ganado|gewinnspiel|sorteio|"
    r"airdrop|空投|代币|"
    r"\bbestellen\b[^.]{0,80}\bab\b)",
    re.IGNORECASE,
)
_DEADLINE_WHEN = re.compile(
    r"\b(?:today|end of (?:the )?day|before the (?:counter|office|window) closes|"
    r"within the hour|by \d{1,2}(?::\d{2})?\s?(?:am|pm)|"
    r"heute|aujourd'hui|hoy|hoje|اليوم|今天)\b",
    re.IGNORECASE,
)
_DEADLINE_WHAT = re.compile(
    r"\b(?:clerk|hearing|court|regulator|exhibit|payroll|statute|venue|"
    r"inquiry|shipment|tribunal|audiencia)\b",
    re.IGNORECASE,
)
_ROLE_LINE = re.compile(
    r"\b(?:producer|recruiter|consultant|coordinator|specialist|analyst|supervisor|"
    r"associate|director|directora|directrice|manager|officer|engineer|founder|"
    r"president|accountant|projektleiter(?:in)?|cheffe|chef|gestor(?:a)?|gerente|"
    r"lead)\b",
    re.IGNORECASE,
)
_ORG_MARK = re.compile(
    r"\b(?:inc|llc|ltd|gmbh|corp|plc|ag|sarl|sas|press|labs|group)\b\.?$",
    re.IGNORECASE,
)
_IDENTITY_STEM = re.compile(r"(?:urgent|outage|emergency|asap|critical)", re.IGNORECASE)
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


_DEFECT = re.compile(
    r"\b(?:not working|is broken|broken|bug|failing|failed|stopped firing|didn't arrive|did not arrive)\b",
    re.IGNORECASE,
)
_DENIED_DEFECT = re.compile(
    r"\bnothing is broken\b|\bnot broken\b|\bisn'?t broken\b|\bno bugs?\b",
    re.IGNORECASE,
)
_COMMERCIAL_ASK = re.compile(
    r"\b(?:quote|quotation|proposal|retainer|budget|sow|statement of work|scope of work|"
    r"presupuesto|devis|or[cç]amento|bütçe|预算)\b",
    re.IGNORECASE,
)


def _defect(text: str) -> bool:
    """A reported fault. 'Nothing is broken' is not one."""
    return bool(_DEFECT.search(_DENIED_DEFECT.sub(" ", text or "")))


# A denial of an outage, or one person's control, is support. A service-wide
# failure is not this shape. The phrases are closed classes, not a mailbox.
_OUTAGE_DENIAL = re.compile(
    r"\bno outage\b|\bnot an outage\b|\bthere is no outage\b"
    r"|\bpas une panne\b|\bpas de panne\b"
    r"|\bn[aã]o [eé] uma queda\b|\bnao e uma queda\b"
    r"|\bsem interrup[cç][aã]o geral\b|\bsem interrupcao geral\b"
    r"|\bkeine st[oö]rung\b|\bkein ausfall\b",
    re.IGNORECASE,
)
_PERSONAL_CONTROL = re.compile(
    r"\b(?:bouton|bot[aã]o|botao|controle|contr[oô]le|control|champ|campo|button)\b",
    re.IGNORECASE,
)
_CONTROL_BROKEN = re.compile(
    r"\b(?:cass[eé]|ne r[eé]pond(?: plus)?|ne repond(?: plus)?|"
    r"n[aã]o responde|nao responde|n[aã]o funciona|nao funciona|"
    r"est[aá] quebrado|esta quebrado|n[aã]o abre|nao abre|is stuck|is broken)\b",
    re.IGNORECASE,
)
_SERVICE_WIDE = re.compile(
    r"\b(?:whole (?:system|service|shop|site)|all customers|"
    r"every (?:user|customer|register|desk)|syst[eè]me entier|sistema inteiro|"
    r"todos os clientes|site is down|hors service)\b",
    re.IGNORECASE,
)
_PROJECT_WORD = re.compile(
    r"\b(?:budget|presupuesto|devis|or[cç]amento|orcamento)\b|予算|ميزانية|预算",
    re.IGNORECASE,
)
_SALARY_SENTENCE = re.compile(
    r"[^.!\n]*\b(?:compensation|salary|gehalt|salaire|salario)\b[^.!\n]*",
    re.IGNORECASE,
)


def _single_seat(text: str) -> bool:
    """A denied outage, or a broken control for one person. Not a service outage."""
    if _SERVICE_WIDE.search(text or ""):
        return False
    if _OUTAGE_DENIAL.search(text or ""):
        return True
    return bool(_PERSONAL_CONTROL.search(text or "") and _CONTROL_BROKEN.search(text or ""))


def _project_budget(text: str) -> str | None:
    """The project figure when a wage is also written. A salary alone is not one."""
    if not _PROJECT_WORD.search(text or ""):
        return None
    return extract_budget(_SALARY_SENTENCE.sub(" ", text or ""))


def _salary_context(text: str) -> bool:
    """A wage, not a project budget. The recruiter label is not required."""
    if _SALARY.search(text or ""):
        return True
    return bool(_SALARY_PERIOD.search(text or "") and re.search(
        r"\b(?:package|salary|compensation|seat|role|gehalt|salaire|salario)\b",
        text or "",
        re.IGNORECASE,
    ))


def _same_day_deadline(text: str) -> bool:
    """A legal or operational deadline dated today. Not an outage template."""
    return bool(_DEADLINE_WHEN.search(text or "") and _DEADLINE_WHAT.search(text or ""))


# Service-down language. A calm support note, however long, is not this.
_OUTAGE_CLAIM = re.compile(
    r"\b(?:outage|offline|unreachable|sev-?1)\b"
    r"|\b(?:is|are|went|goes|going)\s+down\b"
    r"|\bnot taking orders\b"
    r"|\bcannot take (?:bookings|orders|a single sale)\b"
    r"|\bnobody can book\b"
    r"|\bguests cannot reserve\b"
    r"|\bserver error\b"
    r"|\b502s?\b"
    r"|\bleft the queue\b"
    r"|\bwhole shop is stuck\b"
    r"|\bca[ií]d[oa]\b"
    r"|\bno abre para nadie\b"
    r"|\bno podemos recibir\b"
    r"|\bstopped answering\b"
    r"|\bhors service\b"
    r"|\bblank (?:white )?page\b"
    r"|\bfor everyone\b"
    r"|\bevery single\b"
    r"|\bthousands of customers\b"
    r"|\bnothing is (?:printing|shipping)\b"
    r"|\bto the wrong\b"
    r"|\bantwortet nicht\b"
    r"|\bniemand kann\b",
    re.IGNORECASE,
)
# A clock, not a long paragraph. "before noon" on a personal login is not this.
_OPERATIONAL_WHEN = re.compile(
    r"\b(?:within the hour|in (?:\d+|one|two|three|four|five|six) hours?|end of (?:the )?day|"
    r"by \d{1,2}(?::\d{2})?\s?(?:am|pm))\b",
    re.IGNORECASE,
)


def _outage_claim(text: str) -> bool:
    return bool(_OUTAGE_CLAIM.search(text or ""))


def _operational_deadline(text: str) -> bool:
    """An operational deadline. The length of the body does not create one."""
    return bool(_same_day_deadline(text) or _OPERATIONAL_WHEN.search(text or ""))


# Function words, not outage phrases. They only choose which notes trust the head.
_PT_FUNCTION = re.compile(
    r"\b(?:n[aã]o|nao|ning[uú]em|ninguem|nenhum[a]?|voc[eê]s?|voce|tamb[eé]m|tambem|"
    r"obrigad[oa]|manh[aã]|ficou|nest[ea]|ness[ea]|consigo|equipe|hoje)\b|[ãõ]",
    re.IGNORECASE,
)
_UR_FUNCTION = re.compile(
    r"\b(?:hai|hain|nahi|nahin|gaya|gayi|gaye|mein|chahiye|warna|koi|yeh|woh|"
    r"humein|pehle|raha|rahi|rahe|hoon|hoti|jati|leta|kis|kahan|aur)\b",
    re.IGNORECASE,
)
_EN_FUNCTION = re.compile(
    r"\b(?:the|is|are|was|were|please|could|would|with|from|this|that|not|my|our|how|we|you)\b",
    re.IGNORECASE,
)


def _urgency_head_decides(text: str) -> bool:
    """Portuguese, Arabic, Chinese, or romanized Urdu.

    The outage list is mostly English. On these notes the whole-note head is
    the decision. A phrase may still raise urgency. It does not have to match.
    """
    sample = text or ""
    if len(re.findall(r"[\u0600-\u06FF]", sample)) >= 12:
        return True
    hanzi = len(re.findall(r"[\u4e00-\u9fff]", sample))
    kana = len(re.findall(r"[\u3040-\u30ff]", sample))
    if hanzi >= 8 and kana == 0:
        return True
    portuguese = {match.group(0).casefold() for match in _PT_FUNCTION.finditer(sample)}
    urdu = {match.group(0).casefold() for match in _UR_FUNCTION.finditer(sample)}
    english = _EN_FUNCTION.findall(sample)
    if len(portuguese) >= 2 and len(portuguese) >= len(english):
        return True
    if len(urdu) >= 2 and len(urdu) > len(english):
        return True
    return False


def _identity_tokens(email: dict | None) -> list[str]:
    """Sender-name tokens, and a product token that only hides an urgency stem."""
    if not email:
        return []
    found: list[str] = []
    name = email.get("from_name") or ""
    for token in re.findall(r"[^\W\d_]{3,}", name, re.UNICODE):
        found.append(token)
    blob = f"{email.get('subject') or ''}\n{email.get('body') or ''}"
    for token in re.findall(r"[^\W\d_]{4,}", blob, re.UNICODE):
        if token.lower() in {"urgent", "urgently", "urgency", "outage", "emergency", "critical"}:
            continue
        if _IDENTITY_STEM.search(token):
            found.append(token)
    found.extend(re.findall(r"\b[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]+)+\b", blob))
    return found


def _scrub_tokens(text: str, tokens: list[str]) -> str:
    cleaned = text or ""
    for token in tokens:
        if len(token) < 3:
            continue
        cleaned = re.sub(rf"\b{re.escape(token)}\b", " ", cleaned, flags=re.IGNORECASE)
    return cleaned


def _span_urgent(full_text: str, body: str) -> float:
    def _take(text: str, best: float) -> float:
        verdict = assess(text)
        # "Not urgent" is a property of the span. "None of the notices left" is not.
        if (verdict.get("negated") or 0) >= negation_threshold():
            return best
        return max(best, float(verdict.get("urgent") or 0))

    best = _take(full_text or "", 0.0)
    for sentence in _body_sentences(body or ""):
        if len(sentence) < 40:
            continue
        best = _take(sentence, best)
        stripped = re.sub(r"^[A-Za-z][\w.'’-]{1,24},\s+", "", sentence)
        if stripped != sentence and len(stripped) >= 40:
            best = _take(stripped, best)
    return best


def message_urgent(full_text: str, body: str, email: dict | None = None) -> float:
    """Urgency of the whole note, or of one real sentence inside it.

    A greeting and a signature pull the pooled vector off a one-line outage.
    Scoring the body sentences as well keeps that line. Fragments under 40
    characters are skipped so a short calm clause cannot trip the head.
    A leading name is tried both ways, because "Asad," is not the request.
    A token that exists only because it is the sender or the product name
    does not clear the threshold.
    """
    raw = _span_urgent(full_text, body)
    tokens = _identity_tokens(email)
    if not tokens:
        return raw
    scrubbed = _span_urgent(_scrub_tokens(full_text, tokens), _scrub_tokens(body, tokens))
    if raw >= urgency_threshold() and scrubbed < urgency_threshold():
        return scrubbed
    return raw


def full_note_urgent(full_text: str, email: dict | None = None) -> float:
    """Urgency of the whole note, with the same negation and name scrub as the span score.

    One hot sentence inside a calm note does not raise this. A phrase list can
    still raise that sentence. It cannot clear a whole-note hit.
    """

    def _take(text: str) -> float:
        verdict = assess(text or "")
        if (verdict.get("negated") or 0) >= negation_threshold():
            return 0.0
        return float(verdict.get("urgent") or 0)

    raw = _take(full_text or "")
    tokens = _identity_tokens(email)
    if not tokens:
        return raw
    scrubbed = _take(_scrub_tokens(full_text or "", tokens))
    if raw >= urgency_threshold() and scrubbed < urgency_threshold():
        return scrubbed
    return raw


def _body_can_be_urgent(email: dict) -> bool:
    """Urgency needs real prose in the body. A subject line or a calendar blob is not enough."""
    raw = email.get("body") or ""
    if re.search(r"BEGIN:VCALENDAR|text/calendar|METHOD:REQUEST", raw, re.IGNORECASE):
        return False
    prose = strip_quotes(strip_injection_notes(html_to_text(raw)))
    return len(re.sub(r"[^\w]", "", prose, flags=re.UNICODE)) >= 12


def _score(text: str, email: dict, signals: dict | None = None) -> tuple[dict[str, float], list[str]]:
    scores = {name: 0.0 for name in ("lead", "support", "invoice", "spam", "urgent", "recruiter")}
    reasons: list[str] = []
    lowered = text.lower()
    sender = (email.get("from_email") or "").lower()

    def note(label: str) -> None:
        if label not in reasons:
            reasons.append(label)

    if _NEWSLETTER.search(lowered):
        # A clear opt-out, receipt-adjacent promo, or lottery stays spam.
        # The embedding head only fills a gap below 4. Category scores stay regex.
        scores["spam"] += 5
        note("unsubscribe or opt-out")
    if re.search(r"\b(click below to claim|limited time offer|you(?:'ve| have) been selected)\b", lowered):
        scores["spam"] += 5
        note("promotional offer")
    if re.search(
        r"\b(lottery|inheritance|beneficiary|bitcoin giveaway|crypto wallet|viagra|guest post|backlinks?|do-?follow|work from home|seo package|jetons?)\b",
        lowered,
    ):
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
        r"\b(want|looking|need|build|automat|hire|help us|help me|queremos|voudrions|möchten|moechten)\b",
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

    if _defect(lowered):
        scores["support"] += 4
        note("a defect is described")
    if re.search(r"\berror\s?\d{3}\b", lowered):
        scores["support"] += 4
    if re.search(r"\b(password reset|account locked|can't log ?in|cannot log ?in|won't download|blank screen)\b", lowered):
        scores["support"] += 4
    if re.search(r"\b(can you (?:check|look|take a look)|when you have a minute)\b", lowered):
        scores["support"] += 2
    if _SUPPORTISH.search(_DENIED_DEFECT.sub(" ", lowered)):
        scores["support"] += 3
        if not _COMMERCIAL.search(lowered):
            scores["support"] = max(scores["support"], 5.0)
        note("a support question")
    if existing_thread(email) and _SUPPORTISH.search(lowered) and not _COMMERCIAL.search(lowered):
        scores["support"] += 4
        scores["lead"] -= 5
        note("a support thread")
    if not _project_budget(lowered) and (
        _RECRUITER.search(lowered)
        or (
            _salary_context(lowered)
            and not re.search(r"\b(?:quote|proposal|retainer|sow|budget|presupuesto|devis)\b", lowered)
        )
    ):
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
    # The head runs on every note. Phrase lists only raise. On Portuguese,
    # Arabic, Chinese, and romanized Urdu, a whole-note score at or above the
    # threshold stays urgent even when no outage phrase matches. English still
    # needs that phrase or a deadline, so a calm support note stays support.
    # One hot sentence in a long calm body does not count unless a phrase
    # raises it. A picture or a calendar is not urgent.
    negated = signals.get("negated", 0) >= negation_threshold()
    full_hit = float(signals.get("urgent_full", 0) or 0) >= urgency_threshold()
    span_hit = float(signals.get("urgent", 0) or 0) >= urgency_threshold()
    phrase_raises = _same_day_deadline(lowered) or (
        span_hit and (_outage_claim(lowered) or _operational_deadline(lowered))
    )
    decisive = full_hit and _urgency_head_decides(lowered)
    if negated:
        scores["urgent"] = 0
        note("the sender says it is not urgent")
    elif (
        _body_can_be_urgent(email)
        and not _NEWSLETTER.search(lowered)
        and scores["spam"] < 5
        and scores["recruiter"] < 4
        and (decisive or phrase_raises)
    ):
        scores["urgent"] = max(scores["urgent"], 6.0)
        note("customer impact, a security incident, or a same-day deadline")
    if _single_seat(lowered):
        scores["urgent"] = 0
        scores["support"] = max(scores["support"], 6.0)
        note("a single control, not an outage")
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


def _name_script(token: str) -> str:
    letters = [char for char in token if char.isalpha()]
    if not letters:
        return ""
    kinds = set()
    for char in letters:
        code = ord(char)
        if 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF or 0x3040 <= code <= 0x30FF or 0xAC00 <= code <= 0xD7AF:
            kinds.add("cjk")
        elif 0x0600 <= code <= 0x06FF or 0x0750 <= code <= 0x077F or 0x08A0 <= code <= 0x08FF:
            kinds.add("ar")
        else:
            kinds.add("other")
    if kinds == {"cjk"}:
        return "cjk"
    if kinds == {"ar"}:
        return "ar"
    return ""


_LEGAL_SUFFIX = re.compile(
    r"\b(?:inc|llc|ltd|gmbh|corp|corporation|plc|ag|sarl|sas|bv|"
    r"co|limited|incorporated|press|labs|group|partners|counsel)\.?$",
    re.IGNORECASE,
)
_TRUNCATION_LINE = re.compile(r"^\[truncated\]$", re.IGNORECASE)


def is_person(value: str) -> bool:
    # A legal-suffix line is the organization, even when both words are capitalized.
    if _LEGAL_SUFFIX.search((value or "").strip()):
        return False
    tokens = _name_tokens(value)
    if 2 <= len(tokens) <= 4 and all(_name_script(token) in {"cjk", "ar"} for token in tokens):
        return len({_name_script(token) for token in tokens}) == 1
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
        if _TRUNCATION_LINE.match(line.strip()):
            continue
        if sum(character.isdigit() for character in line) >= 7:
            continue
        if is_title(line) or _department(line) or _role_line(line) or "。" in line or "、" in line or _GREETING.match(line):
            continue
        if line.endswith("،"):
            continue
        cleaned = _tidy_company(line)
        if _TRUNCATION_LINE.match(cleaned.strip()):
            continue
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
    # The From line is the organization when it carries a legal suffix.
    # A footer that only repeats a brand ("HubSpot" / "HubSpot, Inc.") stays skipped.
    if _LEGAL_SUFFIX.search(sender) and _company_line(sender.strip()):
        return _tidy_company(sender.strip())
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


def _role_line(line: str) -> bool:
    """A job or a sign-off, not the organization."""
    text = (line or "").strip()
    if not text or _ORG_MARK.search(text):
        return False
    if is_title(text) or _department(text) or _CLOSINGS.match(text):
        return True
    words = re.findall(r"[^\W\d_]+", text, re.UNICODE)
    if words and words[-1].lower() in {"counsel", "partner", "partners"} and len(words) == 2:
        return False
    return bool(_ROLE_LINE.search(text))


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
        if _CLOSINGS.match(line):
            break
        if not line or _GREETING.match(line) or _HEADER_LINE.match(line):
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


def _intent_score(sentence: str) -> int:
    """Prefer the sentence that says the service, the scope, or the timing."""
    low = sentence.casefold()
    score = 0
    for token, weight in (
        ("quote", 5),
        ("devis", 5),
        ("proposal", 4),
        ("retainer", 3),
        ("budget", 2),
        ("service", 3),
        ("broken", 4),
        ("form", 3),
        ("past due", 5),
        ("overdue", 4),
        ("invoice", 2),
        ("down", 3),
        ("error", 2),
        ("today", 1),
        ("tomorrow", 1),
        ("deadline", 2),
    ):
        if token in low:
            score += weight
    if 24 <= len(sentence) <= 180:
        score += 1
    return score


def extract_intent(
    category: str,
    text: str,
    subject: str = "",
    budget: str | None = None,
    name: str | None = None,
    company: str | None = None,
) -> str:
    """One sentence about what the sender wants. Not a fixed template."""
    del budget, name, company
    subject_cf = re.sub(r"\s+", " ", (subject or "").strip()).casefold()
    if category == "suspicious":
        return "Suspicious. Do not pay or reply."
    ranked: list[tuple[int, str]] = []
    for sentence in _body_sentences(text):
        cleaned = re.sub(r"\s+", " ", sentence).strip()
        if not cleaned or _GREETING.match(cleaned):
            continue
        if subject_cf and cleaned.casefold().startswith(subject_cf):
            continue
        ranked.append((_intent_score(cleaned), cleaned))
    if not ranked:
        return "Review the message"
    ranked.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
    echoed = [
        (_intent_score(cleaned), cleaned)
        for sentence in _body_sentences(text)
        if (cleaned := re.sub(r"\s+", " ", sentence).strip())
        and subject_cf
        and cleaned.casefold().startswith(subject_cf)
    ]
    line = ranked[0][1]
    if echoed:
        echoed.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
        if echoed[0][0] >= max(3, ranked[0][0] + 1):
            line = echoed[0][1]
    line = re.sub(
        r"^(?:bonjour|hello|hi|dear|guten tag|hola|ol[aá]|salam)[,!\s]+",
        "",
        line,
        count=1,
        flags=re.IGNORECASE,
    ).strip()
    if len(line) > 140:
        clipped = line[:139].rsplit(" ", 1)[0]
        line = (clipped or line[:139]).rstrip(" ,;:") + "…"
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


def urgent_allowed(
    email: dict,
    text: str,
    known_contacts: list[dict] | None,
    outage_signal: bool = False,
) -> bool:
    """Urgency follows the learned head, for a stranger or a known contact.

    A calendar invite stays out. ``outage_signal`` is accepted when a caller
    already ran the head. A known sender is not required for a deadline.
    """
    del known_contacts
    if not _body_can_be_urgent(email):
        return False
    if outage_signal:
        return True
    body = strip_quotes(strip_injection_notes(html_to_text(email.get("body") or "")))
    return message_urgent(text or "", body, email) >= urgency_threshold()


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
    body_for_urgent = strip_quotes(strip_injection_notes(html_to_text(raw)))
    signals = dict(assess(text))
    # Whole-note score first. Sentence-max can raise a buried outage line.
    # It cannot clear a whole-note hit, and it cannot invent one on its own.
    signals["urgent_full"] = full_note_urgent(text, prepared)
    signals["urgent"] = message_urgent(text, body_for_urgent, prepared)
    if signals["urgent"] > 0:
        # A negated full-text pool must not cancel a sentence the negation head accepts.
        signals["negated"] = 0.0
    flags = assess_risk(prepared, full, raw, [*(known_contacts or []), *(domain_contacts or [])])
    if "lookalike_domain" not in flags and _neighbor_lookalike(prepared, full, domain_contacts):
        flags.append("lookalike_domain")
    contacts = [*(known_contacts or []), *(domain_contacts or [])]
    if decide_suspicious(prepared, full, contacts, signals):
        if "risk_score" not in flags:
            flags.append("risk_score")
    blocking = hard_flags(flags)
    suspicious = bool(blocking)
    visible = dict(prepared)
    visible["body"] = strip_quotes(html_to_text(raw))
    if suspicious:
        category, secondary = "suspicious", []
        confidence = 0.9
        suggested = None
        suggestion_confidence = None
        reasons = []
        name = extract_name(visible, known_contacts)
        company = extract_company(visible, known_contacts)
        budget = None
        intent = "Suspicious. Do not pay or reply."
        scores = None
    else:
        scores, reasons = _score(text, prepared, signals)
        category, secondary, confidence, suggested, suggestion_confidence = _choose(scores)
        # Commercial and recruiting stay their own label. Urgency is secondary.
        # A same-day legal or operational deadline stays urgent.
        if category == "urgent" and not _same_day_deadline(text):
            if scores.get("recruiter", 0) >= 4:
                category = "recruiter"
                secondary = [item for item in secondary if item != "urgent"]
                if scores.get("urgent", 0) >= 4:
                    secondary = [*secondary, "urgent"]
            elif scores.get("lead", 0) >= 4 and (
                _COMMERCIAL_ASK.search(text)
                or (extract_budget(text) and not _salary_context(text))
                or _project_budget(text)
            ):
                category = "lead"
                if "urgent" not in secondary:
                    secondary = [*secondary, "urgent"]
        name = extract_name(visible, known_contacts, accept_display=category not in {"spam", "suspicious"})
        company = extract_company(visible, known_contacts)
        if company is None and category not in {"spam", "suspicious"}:
            company = _company_from_domain(visible)
        auto = (prepared.get("auto_submitted") or "").lower()
        if _OOO.search(prepared.get("subject") or "") or _OOO.search(text) or (auto and auto != "no"):
            name = None
            company = None
        body_only = strip_quotes(strip_injection_notes(html_to_text(prepared.get("body") or "")))
        project = _project_budget(text)
        budget = project or extract_budget(text)
        if project:
            budget = project
        elif budget and (category == "recruiter" or _salary_context(text) or _RECRUITER.search(text)):
            budget = None
        # An organization and a project budget keep the lead label, including
        # when the note is Spanish, German, Arabic, or Japanese and the urgency
        # head is hot. A same-day legal deadline stays urgent.
        if (
            category in {"urgent", "review"}
            and company
            and budget
            and _PROJECT_WORD.search(text)
            and not _same_day_deadline(text)
        ):
            if category == "urgent" and "urgent" not in secondary:
                secondary = [*secondary, "urgent"]
            category = "lead"
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
        if category == "urgent" and not known_sender(prepared, known_contacts) and not existing_thread(prepared):
            if "unverified sender" not in reasons:
                reasons.append("unverified sender")
        overdue = bool(_OVERDUE.search(readable))
        # Overdue on the sender's own invoice adds urgent as a secondary only.
        if category == "invoice" and overdue and "urgent" not in secondary:
            secondary = [*secondary, "urgent"]
            if "overdue invoice" not in reasons:
                reasons.append("overdue invoice")
    # Rank is last, after every secondary label, so a suspicious row cannot keep urgent.
    category, secondary = settle(category, secondary, suspicious)
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
