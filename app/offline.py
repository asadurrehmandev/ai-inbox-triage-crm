"""Small offline classifier. No network, no paid key, a few hundred kilobytes.

A hashed character model is trained on app.synthetic_train, which is not an
evaluation set. A short multilingual lexicon breaks ties when the rules have
nothing to say. The weights live in memory for the process and are never written
back to disk.
"""

from __future__ import annotations

import math
import re
import zlib
from functools import lru_cache

from app.synthetic_train import ROWS

CLASSES = ("lead", "support", "invoice", "spam", "urgent")
_HASH = 2048
_LEX = {
    "lead": (
        r"\b(?:quote|quotation|proposal|retainer|ballpark|discovery call|how much|what would it cost)\b",
        r"cotizaci[oó]n|presupuesto|devis|angebot|or[cç]amento|teklif|offerte",
        r"报价|预算|お見積|ご相談",
    ),
    "support": (
        r"\b(?:not working|doesn't work|does not work|stopped syncing|isn't pushing|is not pushing|is broken|password reset)\b",
        r"no funciona|ne fonctionne pas|funktioniert nicht|n[aã]o funciona|[cç]al[ıi]şm[ıi]yor|werkt niet",
        r"无法|不具合|密码重置",
    ),
    "invoice": (
        r"\b(?:invoice|amount due|payment received|past due)\b",
        r"\bfactura\b|\brechnung\b|\bfatura\b|\bfactuur\b",
        r"发票|請求書|入金",
    ),
    "spam": (
        r"\b(?:unsubscribe|newsletter|webinar|manage preferences)\b",
        r"d[eé]sinscri|abmelden|darte de baja|cancele a inscri",
        r"退订|配信停止|uitschrijven|abonelikten",
    ),
    "urgent": (
        r"\b(?:outage|sev-?1|\bp0\b|production is down|is down|went down|fora do ar)\b",
        r"ca[ií]da|en panne|ausgefallen",
        r"宕机|落ちて|障害",
    ),
}


def _lex_index(label: str) -> int:
    return CLASSES.index(label)


def featurize(text: str) -> dict[int, float]:
    """Sparse counts. Lexicon bits sit in front of the character hash."""
    raw = text or ""
    folded = re.sub(r"\s+", " ", raw.lower())
    feats: dict[int, float] = {}
    for label, patterns in _LEX.items():
        if any(re.search(pattern, raw, re.IGNORECASE) for pattern in patterns):
            feats[_lex_index(label)] = 3.0
    compact = folded.strip()
    for size in (3, 4):
        if len(compact) < size:
            continue
        for index in range(len(compact) - size + 1):
            gram = compact[index : index + size]
            if gram.isspace():
                continue
            slot = len(CLASSES) + (zlib.crc32(gram.encode("utf-8")) % _HASH)
            feats[slot] = min(4.0, feats.get(slot, 0.0) + 1.0)
    return feats


@lru_cache(maxsize=1)
def _model() -> tuple[dict[str, float], dict[str, list[float]]]:
    """Laplace-smoothed log probabilities, trained once per process."""
    dim = len(CLASSES) + _HASH
    counts = {label: [1.0] * dim for label in CLASSES}
    totals = {label: float(dim) for label in CLASSES}
    docs = {label: 1.0 for label in CLASSES}
    for label, text in ROWS:
        if label not in counts:
            continue
        docs[label] += 1.0
        for slot, value in featurize(text).items():
            counts[label][slot] += value
            totals[label] += value
    total_docs = sum(docs.values())
    priors = {label: math.log(docs[label] / total_docs) for label in CLASSES}
    logs = {
        label: [math.log(counts[label][slot] / totals[label]) for slot in range(dim)]
        for label in CLASSES
    }
    return priors, logs


def probabilities(text: str) -> dict[str, float]:
    priors, logs = _model()
    feats = featurize(text)
    raw: dict[str, float] = {}
    for label in CLASSES:
        score = priors[label]
        row = logs[label]
        for slot, value in feats.items():
            score += value * row[slot]
        raw[label] = score
    peak = max(raw.values())
    lifted = {label: math.exp(score - peak) for label, score in raw.items()}
    normal = sum(lifted.values()) or 1.0
    return {label: lifted[label] / normal for label in CLASSES}


def lexicon_label(text: str) -> str | None:
    """One class, when the lexicon hits that class and no other."""
    hits = [
        label
        for label, patterns in _LEX.items()
        if any(re.search(pattern, text or "", re.IGNORECASE) for pattern in patterns)
    ]
    if len(hits) == 1:
        return hits[0]
    return None


def uncertain_label(text: str) -> tuple[str | None, float]:
    """A label and a margin, or (None, 0) when the model is not sure.

    Used only when the keyword rules themselves are below a decision.
    """
    direct = lexicon_label(text)
    if direct:
        return direct, 0.5
    probs = probabilities(text)
    ranked = sorted(probs.items(), key=lambda item: item[1], reverse=True)
    best, top = ranked[0]
    margin = top - ranked[1][1]
    if top >= 0.42 and margin >= 0.12:
        return best, margin
    return None, 0.0
