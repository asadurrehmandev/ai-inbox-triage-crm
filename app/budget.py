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
_CUR = r"(?:USD|US\$|EUR|GBP|\$|€|£)"
_MONEY_WORDS = ("budget", "pay", "spend", "aside", "usd", "eur", "gbp", "dollar", "dollars")

_RANGE = re.compile(
    rf"(?P<c1>{_CUR})\s?(?P<n1>{_NUM})\s*[–—-]\s*(?P<c2>{_CUR})?\s?(?P<n2>{_NUM})",
    re.IGNORECASE,
)
_HOURLY = re.compile(rf"(?P<cur>{_CUR})\s?(?P<num>{_NUM})\s*/\s*hr\b", re.IGNORECASE)
_YEN_MAN = re.compile(r"(?P<num>\d+(?:\.\d+)?)\s*万円")
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
    return {"USD": "$", "EUR": "€", "GBP": "£", "$": "$", "€": "€", "£": "£"}.get(key, "$")


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


def extract_budget(text: str) -> str | None:
    """Return one normalized amount, or None when the text is not naming a price."""
    if not text:
        return None
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
    bare = _BARE_K.search(text)
    if bare and _near_money_word(text, bare.start(), bare.end()):
        clause = text[max(0, bare.start() - 24) : bare.end() + 12]
        symbol = "€" if "€" in clause or re.search(r"\beur\b", clause, re.I) else "$"
        if "£" in clause or re.search(r"\bgbp\b", clause, re.I):
            symbol = "£"
        return _fmt(symbol, float(bare.group("num")) * 1000)
    return None


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
