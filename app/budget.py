"""Money parser. Formats are recognized by shape, not by sample wording."""

from __future__ import annotations

import re

_NUM = (
    r"(?:"
    r"\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?"
    r"|\d{1,3}(?:,\d{3})+(?:\.\d+)?"
    r"|\d+(?:[.,]\d+)?"
    r")"
)
_CUR = r"(?:USD|US\$|EUR|GBP|MXN|BRL|R\$|\$|€|£)"
_MONEY_WORDS = ("budget", "pay", "spend", "aside", "usd", "eur", "gbp", "mxn", "brl", "dollar", "dollars", "quid")
_WORD_VALUES = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_NUMWORD = (
    "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    "sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
)
_WORD_AMOUNT = re.compile(
    rf"\b(?P<words>(?:{_NUMWORD})(?:[-\s]+(?:{_NUMWORD})){{0,3}})\s+"
    rf"(?P<unit>hundred|thousand)(?:\s+(?P<extra>hundred|thousand))?"
    rf"(?:\s+(?:us\s+)?(?P<cur>quid|dollars?|euros?|pounds?|usd|eur|gbp))?",
    re.IGNORECASE,
)
_CORRECTION = re.compile(
    r"\bcorrect\b[^.\n]{0,80}?\bis\b[^.\n]{0,30}?(?P<amt>[$€£]\s?\d[\d,]*(?:\.\d+)?)",
    re.IGNORECASE,
)
_WITHDRAWN = re.compile(
    r"\b(?:ignore|disregard)\b[^.\n]{0,80}?(?P<amt>[$€£]\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s*k\b)",
    re.IGNORECASE,
)
_NOT_AMOUNT = re.compile(
    r"\bnot\s+(?P<amt>[$€£]\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s*k\b)",
    re.IGNORECASE,
)
_THOUSAND_RANGE = re.compile(
    r"\b(?P<a>\d+(?:\.\d+)?)\s*[-–—]\s*(?P<b>\d+(?:\.\d+)?)\s*thousand\b",
    re.IGNORECASE,
)
_THOUSAND = re.compile(r"\b(?P<a>\d+(?:\.\d+)?)\s*thousand\b", re.IGNORECASE)
_BETWEEN_K = re.compile(
    r"\bbetween\s+(?P<a>\d+(?:\.\d+)?)\s+and\s+(?P<b>\d+(?:\.\d+)?)\s*k\b",
    re.IGNORECASE,
)
_REAL = re.compile(rf"R\$\s?(?P<num>{_NUM})", re.IGNORECASE)
_MXN = re.compile(rf"(?:MXN\s?(?P<num>{_NUM})|(?P<num2>{_NUM})\s*MXN)", re.IGNORECASE)
_WORD_TAIL = re.compile(
    rf"(?P<num>{_NUM})\s*(?P<cur>dollars?|bucks|quid|pounds?|euros?|reais)\b",
    re.IGNORECASE,
)

_RANGE = re.compile(
    rf"(?P<c1>{_CUR})\s?(?P<n1>{_NUM})\s*[–—-]\s*(?P<c2>{_CUR})?\s?(?P<n2>{_NUM})",
    re.IGNORECASE,
)
_HOURLY = re.compile(rf"(?P<cur>{_CUR})\s?(?P<num>{_NUM})\s*/\s*hr\b", re.IGNORECASE)
_YEN_MAN = re.compile(r"(?P<num>\d+(?:\.\d+)?)\s*万円")
_YEN_MARK = re.compile(r"(?:¥|￥)\s*(?P<num>\d[\d,]*)|(?P<num2>\d[\d,]*)\s*円")
_YUAN = re.compile(r"(?P<num>\d[\d,]*)\s*元|(?:RMB|CNY)\s*(?P<num2>\d[\d,]*)")
_NAMED_CURRENCY = re.compile(
    rf"(?:(?P<code>TRY|TL|PKR|SEK|CHF|AUD|CAD|INR|PLN|NOK|DKK|SGD|NZD|AED)\s*(?P<num>{_NUM})"
    rf"|(?P<num2>{_NUM})\s*(?P<code2>TRY|TL|PKR|SEK|CHF|AUD|CAD|INR|PLN|NOK|DKK|SGD|NZD|AED|kr)\b"
    rf"|(?<![A-Za-z])Rs\.?(?![A-Za-z])\s*(?P<num3>{_NUM})|(?P<num4>{_NUM})\s*Rs\.?(?![A-Za-z]))",
    re.IGNORECASE,
)
_GRAND = re.compile(r"(?<![A-Za-z])(?P<num>\d+(?:\.\d+)?)\s*grand\b", re.IGNORECASE)
_PREFIX = re.compile(rf"(?P<cur>{_CUR})\s?(?P<num>{_NUM})(?!\s*k\b)", re.IGNORECASE)
_SUFFIX = re.compile(rf"(?P<num>{_NUM})\s?(?P<cur>USD|EUR|GBP|€|£|\$)", re.IGNORECASE)
_SYMBOL_K = re.compile(rf"(?P<cur>\$|€|£)\s?(?P<num>\d+(?:\.\d+)?)\s*k\b", re.IGNORECASE)
_BARE_K = re.compile(r"(?<![A-Za-z$€£])(?P<num>\d+(?:\.\d+)?)\s*k(?:-ish)?\b", re.IGNORECASE)


def parse_number(raw: str) -> float:
    compact = raw.strip().replace("\u00a0", " ")
    if re.fullmatch(r"\d{1,3}(?: \d{3})+(?:,\d+)?", compact):
        compact = compact.replace(" ", "")
        if "," in compact:
            compact = compact.replace(",", ".")
        return float(compact)
    compact = compact.replace(" ", "")
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", compact):
        compact = compact.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", compact):
        compact = compact.replace(",", "")
    elif re.fullmatch(r"\d+,\d{1,2}", compact):
        compact = compact.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", compact):
        compact = compact.replace(".", "")
    else:
        compact = compact.replace(",", "")
    return float(compact)


def _symbol(token: str) -> str:
    key = token.upper().replace("US$", "USD")
    return {
        "USD": "$", "EUR": "€", "GBP": "£", "BRL": "R$", "MXN": "MXN",
        "DOLLAR": "$", "DOLLARS": "$", "BUCKS": "$", "QUID": "£", "POUND": "£", "POUNDS": "£",
        "EURO": "€", "EUROS": "€", "REAIS": "R$",
        "$": "$", "€": "€", "£": "£", "R$": "R$",
    }.get(key, "$")


def _fmt(symbol: str, value: float, hourly: bool = False) -> str:
    if abs(value - round(value)) < 0.001:
        text = f"{symbol}{int(round(value)):,}"
    else:
        text = f"{symbol}{value:,.2f}"
    return text + ("/hr" if hourly else "")


def _near_money_word(text: str, start: int, end: int) -> bool:
    """A bare '5k' counts only when a money word shares its sentence, within five tokens."""
    cuts = [text.rfind(mark, 0, start) for mark in (".", "!", "?", "\n")]
    sentence_start = max(cuts) + 1
    tail = text[end:]
    stops = [tail.find(mark) for mark in (".", "!", "?", "\n") if tail.find(mark) != -1]
    sentence_end = end + (min(stops) if stops else len(tail))
    before = re.findall(r"[A-Za-z$€£]+", text[sentence_start:start].lower())[-5:]
    after = re.findall(r"[A-Za-z$€£]+", text[end:sentence_end].lower())[:5]
    return any(token in _MONEY_WORDS or token in {"$", "€", "£"} for token in before + after)


def _word_number(token: str) -> float | None:
    return _WORD_VALUES.get(token.lower())


def _spoken_value(match: re.Match) -> float | None:
    total = 0.0
    for part in re.split(r"[-\s]+", match.group("words").lower()):
        value = _word_number(part)
        if value is None:
            return None
        total += value
    unit = match.group("unit").lower()
    factor = 100 if unit == "hundred" else 1000
    extra = (match.group("extra") or "").lower()
    if extra == "thousand":
        factor *= 1000
    elif extra == "hundred":
        factor *= 100
    return total * factor


def _blank_span(text: str, start: int, end: int) -> str:
    return text[:start] + (" " * (end - start)) + text[end:]


def _without_withdrawn(text: str) -> str:
    """Drop amounts the sender tells the reader to ignore, including 'not $X'."""
    for pattern in (_WITHDRAWN, _NOT_AMOUNT):
        while True:
            match = pattern.search(text)
            if not match:
                break
            text = _blank_span(text, match.start("amt"), match.end("amt"))
    return text


def _range(symbol: str, left: float, right: float) -> str:
    return f"{_fmt(symbol, left)}–{_fmt(symbol, right)}"


def extract_budget(text: str) -> str | None:
    """Return one normalized amount, or None when the text is not naming a price."""
    if not text:
        return None
    corrected = _CORRECTION.search(text)
    if corrected:
        return _fmt(_symbol(corrected.group("amt")[:1]), parse_number(re.sub(r"[^\d.,]", "", corrected.group("amt"))))
    text = _without_withdrawn(text)
    words = _WORD_AMOUNT.search(text)
    spoken = _spoken_value(words) if words else None
    if spoken is not None:
        symbol = _symbol(words.group("cur") or "$")
        if not words.group("cur") and re.search(r"\beuros?\b", text[words.end() : words.end() + 24], re.I):
            symbol = "€"
        return _fmt(symbol, spoken)
    thousand_range = _THOUSAND_RANGE.search(text)
    if thousand_range:
        symbol = "€" if re.search(r"\beuros?\b", text, re.I) else "$"
        if re.search(r"\b(quid|pounds?)\b", text, re.I):
            symbol = "£"
        return _range(symbol, float(thousand_range.group("a")) * 1000, float(thousand_range.group("b")) * 1000)
    between = _BETWEEN_K.search(text)
    if between:
        symbol = "€" if re.search(r"\beuros?\b", text, re.I) else "$"
        if re.search(r"\b(quid|pounds?)\b", text, re.I):
            symbol = "£"
        return _range(symbol, float(between.group("a")) * 1000, float(between.group("b")) * 1000)
    real = _REAL.search(text)
    if real:
        return _fmt("R$", parse_number(real.group("num")))
    mxn = _MXN.search(text)
    if mxn:
        return _fmt("MXN", parse_number(mxn.group("num") or mxn.group("num2")))
    yen_mark = _YEN_MARK.search(text)
    if yen_mark:
        return _fmt("¥", parse_number(yen_mark.group("num") or yen_mark.group("num2")))
    named = _NAMED_CURRENCY.search(text)
    if named:
        code = (named.group("code") or named.group("code2") or "").upper()
        if named.group("num3") or named.group("num4"):
            code = "Rs"
        raw = named.group("num") or named.group("num2") or named.group("num3") or named.group("num4")
        amount = parse_number(raw)
        label = {"TL": "TRY"}.get(code, code)
        if abs(amount - round(amount)) < 0.001:
            return f"{label} {int(round(amount)):,}"
        return f"{label} {amount:,.2f}"
    yuan = _YUAN.search(text)
    if yuan:
        amount = parse_number(yuan.group("num") or yuan.group("num2"))
        if abs(amount - round(amount)) < 0.001:
            return f"{int(round(amount)):,}元"
        return f"{amount:,.2f}元"
    thousand = _THOUSAND.search(text)
    if thousand:
        return _fmt("$", float(thousand.group("a")) * 1000)
    ranged = _RANGE.search(text)
    if ranged:
        symbol = _symbol(ranged.group("c1"))
        left = _fmt(symbol, parse_number(ranged.group("n1")))
        right_symbol = _symbol(ranged.group("c2") or ranged.group("c1"))
        right = _fmt(right_symbol, parse_number(ranged.group("n2")))
        return f"{left}–{right}"
    hourly = _HOURLY.search(text)
    if hourly:
        return _fmt(_symbol(hourly.group("cur")), parse_number(hourly.group("num")), hourly=True)
    yen = _YEN_MAN.search(text)
    if yen:
        return _fmt("¥", float(yen.group("num")) * 10_000)
    grand = _GRAND.search(text)
    if grand:
        return _fmt("$", float(grand.group("num")) * 1000)
    symbol_k = _SYMBOL_K.search(text)
    if symbol_k:
        return _fmt(_symbol(symbol_k.group("cur")), float(symbol_k.group("num")) * 1000)
    prefix = _PREFIX.search(text)
    suffix = _SUFFIX.search(text)
    chosen = _prefer_amount(text, prefix, suffix)
    if chosen:
        return chosen
    spoken = _WORD_TAIL.search(text)
    if spoken:
        return _fmt(_symbol(spoken.group("cur")), parse_number(spoken.group("num")))
    bare = _BARE_K.search(text)
    if bare and _near_money_word(text, bare.start(), bare.end()):
        clause = text[max(0, bare.start() - 24) : bare.end() + 12]
        symbol = "€" if "€" in clause or re.search(r"\beur\b", clause, re.I) else "$"
        if "£" in clause or re.search(r"\bgbp\b", clause, re.I):
            symbol = "£"
        return _fmt(symbol, float(bare.group("num")) * 1000)
    return None


def amount_withdrawn(claimed: str, text: str) -> bool:
    """True when this amount sits in an ignore, disregard, or 'not $X' correction."""
    match = re.search(r"\d[\d,]*", (claimed or "").replace(" ", ""))
    if not match or not text:
        return False
    digits = match.group(0).replace(",", "")
    for pattern in (_WITHDRAWN, _NOT_AMOUNT):
        for hit in pattern.finditer(text):
            raw = re.sub(r"[^\d]", "", hit.group("amt"))
            if raw == digits:
                return True
    return False


def amount_in_text(claimed: str, visible: str) -> bool:
    """True when the claimed amount is written in the visible message, not only invented."""
    if not claimed or not visible:
        return False
    if claimed.casefold() in visible.casefold():
        return True
    match = re.search(r"\d[\d,]*", claimed.replace(" ", ""))
    if not match:
        return False
    digits = match.group(0).replace(",", "")
    for token in re.findall(r"\d[\d.,]*", visible):
        compact = re.sub(r"[.,](?=\d{3}(?:\D|$))", "", token).replace(",", "").replace(".", "")
        if compact == digits:
            return True
    return False


def _prefer_amount(text: str, prefix: re.Match | None, suffix: re.Match | None) -> str | None:
    candidates = [match for match in (prefix, suffix) if match]
    if not candidates:
        return None
    # Prefer the amount that sits nearest a money word. Otherwise take the first.
    def rank(match: re.Match) -> tuple[int, int]:
        window = text[max(0, match.start() - 40) : match.end() + 40].lower()
        near = 0 if any(word in window for word in _MONEY_WORDS) else 1
        return (near, match.start())

    match = sorted(candidates, key=rank)[0]
    return _fmt(_symbol(match.group("cur")), parse_number(match.group("num")))
