"""Train the label, urgency, money, and risk heads. Prints held-out metrics."""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

import numpy as np

from app.corpus import BENIGN_MONEY, LABELS, LURES, rows
from app.embedder import embed

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "app" / "model_weights.json"
METRICS = ROOT / "app" / "heldout_metrics.json"


def _softmax(x: np.ndarray, y: np.ndarray, k: int, lr: float = 0.5, epochs: int = 240, l2: float = 0.02):
    n, d = x.shape
    weights = np.zeros((k, d), dtype=np.float64)
    bias = np.zeros(k, dtype=np.float64)
    for _ in range(epochs):
        logits = x @ weights.T + bias
        logits -= logits.max(axis=1, keepdims=True)
        probs = np.exp(logits)
        probs /= probs.sum(axis=1, keepdims=True)
        target = np.zeros_like(probs)
        target[np.arange(n), y] = 1.0
        grad = (probs - target) / n
        weights -= lr * (grad.T @ x + l2 * weights)
        bias -= lr * grad.sum(axis=0)
    return weights, bias


def _sigmoid(x: np.ndarray, y: np.ndarray, lr: float = 1.2, epochs: int = 360, l2: float = 1e-4):
    n, d = x.shape
    weights = np.zeros(d, dtype=np.float64)
    bias = 0.0
    target = y.astype(np.float64)
    for _ in range(epochs):
        raw = x @ weights + bias
        probs = 1.0 / (1.0 + np.exp(-np.clip(raw, -20, 20)))
        grad = (probs - target) / n
        weights -= lr * (x.T @ grad + l2 * weights)
        bias -= lr * float(grad.sum())
    return weights, bias


def _predict_label(x: np.ndarray, weights: np.ndarray, bias: np.ndarray) -> np.ndarray:
    logits = x @ weights.T + bias
    return logits.argmax(axis=1)


def _predict_sigmoid(x: np.ndarray, weights: np.ndarray, bias: float) -> np.ndarray:
    raw = x @ weights + bias
    return 1.0 / (1.0 + np.exp(-np.clip(raw, -20, 20)))


def _balance(items: list[dict], cap: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    buckets: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        buckets[item["label"]].append(item)
    kept: list[dict] = []
    for label in LABELS:
        pool = buckets[label]
        rng.shuffle(pool)
        kept.extend(pool[:cap])
    return kept


def _risk_matrix() -> tuple[np.ndarray, np.ndarray, list[str]]:
    keys = ["known", "free_mail", "claims_org", "lookalike", "link_mismatch", "shortener", "money", "urgency", "aligned"]
    positive = [
        {"money": 1, "free_mail": 1, "link_mismatch": 1},
        {"money": 1, "free_mail": 1, "shortener": 1},
        {"money": 1, "free_mail": 1, "claims_org": 1},
        {"money": 1, "lookalike": 1},
        {"money": 1, "lookalike": 1, "urgency": 1},
        {"money": 1, "link_mismatch": 1, "urgency": 1},
        {"money": 1, "shortener": 1, "claims_org": 1, "free_mail": 1},
        {"money": 1, "free_mail": 1, "urgency": 1, "claims_org": 1},
    ]
    negative = [
        {"aligned": 1},
        {"aligned": 1, "money": 1},
        {"aligned": 1, "urgency": 1},
        {"known": 1, "aligned": 1, "urgency": 1},
        {"free_mail": 1},
        {"urgency": 1},
        {"known": 1, "money": 0, "aligned": 1},
        {"lookalike": 0, "money": 0, "link_mismatch": 1},
    ]
    rows_x = []
    rows_y = []
    for block, label in ((positive, 1.0), (negative, 0.0)):
        for item in block:
            rows_x.append([float(item.get(key, 0.0)) for key in keys])
            rows_y.append(label)
    return np.asarray(rows_x, dtype=np.float64), np.asarray(rows_y, dtype=np.float64), keys


def main() -> None:
    data = rows()
    texts = [item["text"] for item in data]
    print(f"embedding {len(texts)} synthetic rows")
    vectors = []
    batch = 32
    for start in range(0, len(texts), batch):
        vectors.append(embed(texts[start : start + batch], max_length=128))
        if start and start % 320 == 0:
            print(f"  {start}/{len(texts)}")
    matrix = np.vstack(vectors)
    train_index = [i for i, item in enumerate(data) if not item["heldout"]]
    held_index = [i for i, item in enumerate(data) if item["heldout"]]
    train_items = [data[i] for i in train_index]
    balanced = _balance(train_items, cap=280, seed=7)
    by_text = {item["text"]: matrix[i] for i, item in enumerate(data)}
    x_train = np.vstack([by_text[item["text"]] for item in balanced])
    y_train = np.asarray([LABELS.index(item["label"]) for item in balanced], dtype=np.int64)
    mean = x_train.mean(axis=0)
    x_train = x_train - mean
    label_w, label_b = _softmax(x_train, y_train, len(LABELS), l2=1e-3)

    def urgency_xy(key: str):
        pool = [data[i] for i in train_index]
        positives = [item for item in pool if item[key]]
        negatives = [item for item in pool if not item[key]]
        rng = random.Random(11)
        rng.shuffle(negatives)
        chosen = positives + negatives[: len(positives)]
        xs = [(by_text[item["text"]] - mean) for item in chosen]
        ys = [item[key] for item in chosen]
        return np.vstack(xs), np.asarray(ys, dtype=np.float64)

    urgency = {}
    urgency_w = {}
    for key in ("outage", "explicit", "negated"):
        xs, ys = urgency_xy(key)
        weights, bias = _sigmoid(xs, ys)
        urgency[key] = {"weights": weights.tolist(), "bias": bias}
        urgency_w[key] = (weights, bias)

    lure_texts = [f"{prefix} {text}" for prefix in ("", "Please read.", "Accounts:") for text in LURES]
    benign_texts = [f"{prefix} {text}" for prefix in ("", "Hello.", "Accounts:") for text in BENIGN_MONEY]
    money_x = np.vstack([embed(lure_texts, max_length=96), embed(benign_texts, max_length=96)]) - mean
    money_y = np.asarray([1.0] * len(lure_texts) + [0.0] * len(benign_texts))
    money_w, money_b = _sigmoid(money_x, money_y, lr=1.5, epochs=500, l2=1e-4)
    lure_p = _predict_sigmoid(money_x[: len(lure_texts)], money_w, money_b)
    benign_p = _predict_sigmoid(money_x[len(lure_texts) :], money_w, money_b)
    threshold = 0.5
    lure_sim = lure_p
    benign_sim = benign_p

    risk_x, risk_y, risk_keys = _risk_matrix()
    risk_w, risk_b = _sigmoid(risk_x, risk_y, lr=0.8, epochs=400, l2=0.01)
    # A high bar so the hard combination, not a lone feature, is what fires.
    risk_threshold = 0.8

    held_x = matrix[held_index] - mean
    held_y = np.asarray([LABELS.index(data[i]["label"]) for i in held_index])
    predicted = _predict_label(held_x, label_w, label_b)
    label_hit = int((predicted == held_y).sum())
    outage_y = np.asarray([data[i]["outage"] for i in held_index], dtype=np.float64)
    outage_p = _predict_sigmoid(held_x, *urgency_w["outage"])
    outage_hat = outage_p >= 0.5
    outage_total = int(outage_y.sum())
    outage_hit = int(((outage_hat == 1) & (outage_y == 1)).sum())
    negated_y = np.asarray([data[i]["negated"] for i in held_index])
    negated_p = _predict_sigmoid(held_x, *urgency_w["negated"])
    negated_total = int(negated_y.sum())
    negated_hit = int(((negated_p >= 0.5) & (negated_y == 1)).sum())
    # Deadlines are explicit and must not be called outages.
    deadline = np.asarray([data[i]["explicit"] == 1 and data[i]["outage"] == 0 for i in held_index])
    deadline_false = int(((outage_p >= 0.5) & deadline).sum())
    deadline_n = int(deadline.sum())

    payload = {
        "model": "intfloat/multilingual-e5-small",
        "label": {
            "labels": list(LABELS),
            "weights": label_w.tolist(),
            "bias": label_b.tolist(),
        },
        "urgency": urgency,
        "mean": mean.astype(float).tolist(),
        "money": {
            "weights": money_w.astype(float).tolist(),
            "bias": float(money_b),
            "threshold": threshold,
            "lure_recall": float((lure_p >= 0.5).mean()),
            "benign_false": float((benign_p >= 0.5).mean()),
        },
        "risk": {
            "keys": risk_keys,
            "weights": {key: float(weight) for key, weight in zip(risk_keys, risk_w, strict=True)},
            "bias": float(risk_b),
            "threshold": risk_threshold,
        },
    }
    OUT.write_text(json.dumps(payload), encoding="utf-8")
    metrics = {
        "rows": len(data),
        "train_rows": len(train_index),
        "heldout_rows": len(held_index),
        "label_accuracy": label_hit / max(len(held_index), 1),
        "label_correct": label_hit,
        "label_total": len(held_index),
        "outage_recall": outage_hit / max(outage_total, 1),
        "outage_correct": outage_hit,
        "outage_total": outage_total,
        "negation_recall": negated_hit / max(negated_total, 1),
        "negation_correct": negated_hit,
        "negation_total": negated_total,
        "deadline_called_outage": deadline_false,
        "deadline_total": deadline_n,
        "money_threshold": threshold,
        "lure_recall": float((lure_sim >= 0.5).mean()),
        "lure_min": float(lure_sim.min()),
        "benign_false": float((benign_sim >= 0.5).mean()),
        "benign_max": float(benign_sim.max()),
    }
    METRICS.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
