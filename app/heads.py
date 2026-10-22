"""Label, urgency, and ask heads on the fine-tuned multilingual embedding.

The upper encoder layers are a SetFit-style fine-tune stored beside the
pinned base model. The linear heads are trained on ``app.corpus``, split by
scenario group. ``data/hand_heldout.json`` is not part of that training.
Weights live in ``app/model_weights.json``. A missing file leaves the heads
silent so the structural rules still run.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.embedder import embed_one

WEIGHTS = Path(__file__).resolve().parent / "model_weights.json"
LABELS = ("lead", "support", "invoice", "recruiter", "spam", "personal", "other")


@lru_cache(maxsize=1)
def _weights() -> dict:
    if not WEIGHTS.exists():
        return {}
    return json.loads(WEIGHTS.read_text(encoding="utf-8"))


def _dot(vector: np.ndarray, row: list[float], bias: float) -> float:
    total = bias
    for index, weight in enumerate(row):
        total += float(vector[index]) * float(weight)
    return total


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


@lru_cache(maxsize=512)
def assess(text: str) -> dict:
    """One embedding, then the label, urgency, and money scores."""
    loaded = _weights()
    if not loaded:
        return {
            "label": None,
            "label_p": 0.0,
            "outage": 0.0,
            "explicit": 0.0,
            "negated": 0.0,
            "money_sim": 0.0,
        }
    vector = np.asarray(embed_one(text or ""), dtype=np.float32)
    center = loaded.get("mean")
    if center:
        vector = vector - np.asarray(center, dtype=np.float32)
    label_block = loaded["label"]
    logits = [
        _dot(vector, row, bias)
        for row, bias in zip(label_block["weights"], label_block["bias"], strict=True)
    ]
    peak = max(logits)
    lifted = [math.exp(item - peak) for item in logits]
    normal = sum(lifted) or 1.0
    probs = [item / normal for item in lifted]
    best = max(range(len(probs)), key=probs.__getitem__)
    urgency = loaded.get("urgency") or {}
    urgent_block = urgency.get("urgent") or urgency.get("outage") or {"weights": [], "bias": 0.0}
    negated_block = urgency.get("negated") or {"weights": [], "bias": 0.0}
    ask = loaded.get("ask") or {}
    money = ask.get("money") or loaded.get("money") or {}

    def _head(block: dict) -> float:
        if not block.get("weights"):
            return 0.0
        return _sigmoid(_dot(vector, block["weights"], block.get("bias", 0.0)))

    return {
        "label": LABELS[best],
        "label_p": probs[best],
        "urgent": _head(urgent_block),
        "negated": _head(negated_block),
        "money_sim": _head(money),
        "bank_sim": _head(ask.get("bank") or {}),
        "credential_sim": _head(ask.get("credential") or {}),
    }


def risk_probability(features: dict[str, float]) -> float:
    loaded = _weights()
    block = loaded.get("risk") if loaded else None
    if not block:
        return 0.0
    total = float(block["bias"])
    for key, weight in block["weights"].items():
        total += float(weight) * float(features.get(key, 0.0))
    return _sigmoid(total)


def urgency_threshold() -> float:
    loaded = _weights()
    urgent = ((loaded.get("urgency") or {}).get("urgent") or {}) if loaded else {}
    return float(urgent.get("threshold", 1.0))


def negation_threshold() -> float:
    loaded = _weights()
    negated = ((loaded.get("urgency") or {}).get("negated") or {}) if loaded else {}
    return float(negated.get("threshold", 1.0))


def ask_threshold() -> float:
    loaded = _weights()
    ask = (loaded.get("ask") or {}) if loaded else {}
    return float(ask.get("threshold", 1.0))


def money_threshold() -> float:
    loaded = _weights()
    if not loaded:
        return 1.0
    return float(loaded.get("money", {}).get("threshold", 1.0))


def risk_threshold() -> float:
    loaded = _weights()
    if not loaded:
        return 1.0
    return float(loaded.get("risk", {}).get("threshold", 1.0))
