"""Label, urgency, and money heads on top of the multilingual embedding.

The heads are a softmax and three sigmoids trained on ``app.corpus``, which is
synthetic and is not an evaluation mailbox. Weights live in
``app/model_weights.json``. A missing file leaves the heads silent so the
structural rules still run.
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
    urgency = loaded["urgency"]
    money = loaded["money"]
    if money.get("weights"):
        money_sim = _sigmoid(_dot(vector, money["weights"], money["bias"]))
    else:
        centroid = np.asarray(money["centroid"], dtype=np.float32)
        money_sim = float(np.dot(vector, centroid))
    return {
        "label": LABELS[best],
        "label_p": probs[best],
        "outage": _sigmoid(_dot(vector, urgency["outage"]["weights"], urgency["outage"]["bias"])),
        "explicit": _sigmoid(_dot(vector, urgency["explicit"]["weights"], urgency["explicit"]["bias"])),
        "negated": _sigmoid(_dot(vector, urgency["negated"]["weights"], urgency["negated"]["bias"])),
        "money_sim": money_sim,
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
