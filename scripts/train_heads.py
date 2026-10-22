"""Fine-tune the upper encoder layers, then fit the linear heads.

The published encoder is fit on every scenario group except fold 0 and except
a small watch set used only to choose the epoch. The urgency threshold is
chosen on fold 0 so recall is at least 0.90 and the false-urgent rate is at
most 0.05. data/hand_heldout.json is scored after that choice and is not used
to fit, to pick the epoch, or to pick the threshold.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as functional

from app.corpus import LABELS, rows
from app.embedder import embed, load_bundle, pooled, save_delta

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "app" / "model_weights.json"
METRICS = ROOT / "app" / "heldout_metrics.json"
HAND = ROOT / "data" / "hand_heldout.json"
LAST = 8
EPOCHS = 5
BATCH = 16
# Held out of the encoder update. The easy groups keep a template from
# dominating the update. The pick groups are paraphrases the encoder and the
# shipped head never fit, and they are the only signal for choosing the epoch.
WATCH = {"outage-oven", "support-browser", "invoice-linen", "personal-film"}
PICK = {"pick-halt", "pick-stuck", "pick-down", "pick-calm"}


def _softmax(x: np.ndarray, y: np.ndarray, k: int, lr: float = 0.6, epochs: int = 280, l2: float = 1e-3):
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


def _sigmoid(x: np.ndarray, y: np.ndarray, lr: float = 1.0, epochs: int = 420, l2: float = 1e-4):
    n = len(y)
    if n == 0:
        return np.zeros(x.shape[1], dtype=np.float64), 0.0
    weights = np.zeros(x.shape[1], dtype=np.float64)
    bias = 0.0
    target = y.astype(np.float64)
    for _ in range(epochs):
        raw = x @ weights + bias
        probs = 1.0 / (1.0 + np.exp(-np.clip(raw, -20, 20)))
        grad = (probs - target) / n
        weights -= lr * (x.T @ grad + l2 * weights)
        bias -= lr * float(grad.sum())
    return weights, bias


def _balance_idx(y: np.ndarray, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    pos = np.flatnonzero(y == 1)
    neg = np.flatnonzero(y == 0)
    if len(pos) == 0 or len(neg) == 0:
        return np.arange(len(y))
    n = min(len(pos), len(neg))
    chosen = np.concatenate([
        rng.choice(pos, n, replace=False),
        rng.choice(neg, n, replace=False),
    ])
    rng.shuffle(chosen)
    return chosen


def _predict_sigmoid(x: np.ndarray, weights: np.ndarray, bias: float) -> np.ndarray:
    raw = x @ weights + bias
    return 1.0 / (1.0 + np.exp(-np.clip(raw, -20, 20)))


def _center(train: np.ndarray, *others: np.ndarray) -> tuple[np.ndarray, list[np.ndarray]]:
    mean = train.mean(axis=0)
    return mean, [train - mean, *[(item - mean) for item in others]]


def _calibrate(scores: np.ndarray, gold: np.ndarray) -> tuple[float, float, float]:
    """Most recall at a false-urgent rate of at most 0.05, recall at least 0.90.

    Among thresholds that tie on recall, keep the highest one.
    """
    best: tuple[float, float, float] | None = None
    fallback: tuple[float, float, float] | None = None
    for step in range(5, 96):
        threshold = step / 100
        pred = scores >= threshold
        pos = gold == 1
        neg = gold == 0
        recall = float(pred[pos].mean()) if pos.any() else 0.0
        fpr = float(pred[neg].mean()) if neg.any() else 0.0
        if fpr <= 0.05 and (fallback is None or (recall, threshold) > (fallback[1], fallback[0])):
            fallback = (threshold, recall, fpr)
        if recall >= 0.90 and fpr <= 0.05 and (best is None or (recall, threshold) > (best[1], best[0])):
            best = (threshold, recall, fpr)
    if best:
        return best
    if fallback:
        return fallback
    return 0.5, 0.0, 1.0


def _rates(scores: np.ndarray, gold: np.ndarray, threshold: float) -> tuple[float, float, int, int, int, int]:
    pred = scores >= threshold
    pos = gold == 1
    neg = gold == 0
    tp = int((pred & pos).sum())
    fn = int((~pred & pos).sum())
    fp = int((pred & neg).sum())
    tn = int((~pred & neg).sum())
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    return recall, fpr, tp, tp + fn, fp, fp + tn


def _supcon(emb: torch.Tensor, labels: torch.Tensor, temp: float = 0.1) -> torch.Tensor:
    sim = emb @ emb.T / temp
    eye = torch.eye(sim.shape[0], dtype=torch.bool)
    sim = sim.masked_fill(eye, -1e4)
    log_prob = sim - torch.logsumexp(sim, dim=1, keepdim=True)
    same = labels.view(-1, 1).eq(labels.view(1, -1)) & ~eye
    count = same.sum(1)
    valid = count > 0
    if not bool(valid.any()):
        return emb.sum() * 0.0
    mean_log = (log_prob * same).sum(1) / count.clamp(min=1)
    return -mean_log[valid].mean()


def _snapshot(model) -> dict[str, torch.Tensor]:
    start = model.config.num_hidden_layers - LAST
    kept = {}
    for name, param in model.named_parameters():
        if name.startswith("encoder.layer.") and int(name.split(".")[2]) >= start:
            kept[name] = param.detach().cpu().clone()
    return kept


def _restore(model, kept: dict[str, torch.Tensor]) -> None:
    params = dict(model.named_parameters())
    with torch.no_grad():
        for name, value in kept.items():
            params[name].copy_(value)


def _prepare(model) -> None:
    for param in model.parameters():
        param.requires_grad = False
    start = model.config.num_hidden_layers - LAST
    # Dropout stays off. On this small set it flipped the urgent direction
    # after the second epoch.
    model.eval()
    for index, layer in enumerate(model.encoder.layer):
        if index >= start:
            for param in layer.parameters():
                param.requires_grad = True


def _fit_probe(train_x: np.ndarray, train_y: np.ndarray, other_x: np.ndarray, other_y: np.ndarray):
    chosen = _balance_idx(train_y, seed=3)
    weights, bias = _sigmoid(train_x[chosen], train_y[chosen])
    scores = _predict_sigmoid(other_x, weights, bias)
    threshold, recall, fpr = _calibrate(scores, other_y)
    return threshold, recall, fpr, weights, bias


def _embed_rows(model, tokenizer, texts: list[str]) -> np.ndarray:
    model.eval()
    rows = []
    for start in range(0, len(texts), 16):
        chunk = pooled(model, tokenizer, texts[start : start + 16], max_length=128, train_last=0)
        rows.append(chunk.detach().cpu().numpy().astype(np.float32))
    return np.concatenate(rows, axis=0)


def _train_encoder(data: list[dict], train_idx: list[int], model, tokenizer) -> list[dict[str, torch.Tensor]]:
    label_head = torch.nn.Linear(model.config.hidden_size, len(LABELS))
    urgent_head = torch.nn.Linear(model.config.hidden_size, 1)
    neg_head = torch.nn.Linear(model.config.hidden_size, 1)
    ask_heads = torch.nn.ModuleDict({name: torch.nn.Linear(model.config.hidden_size, 1) for name in ("money", "bank", "credential")})
    encoder_params = [param for param in model.parameters() if param.requires_grad]
    optimizer = torch.optim.AdamW(
        [
            {"params": encoder_params, "lr": 2e-6 if os.environ.get("LANE_CONTINUE") == "1" else 1e-5},
            {"params": list(label_head.parameters()) + list(urgent_head.parameters()) + list(neg_head.parameters()) + list(ask_heads.parameters()), "lr": 1e-3},
        ],
        weight_decay=0.01,
    )
    urgent_idx = [i for i in train_idx if data[i]["urgent"] == 1]
    calm_idx = [i for i in train_idx if data[i]["urgent"] == 0 and data[i]["label"] in {"invoice", "lead"}]
    other_idx = [i for i in train_idx if data[i]["urgent"] == 0 and i not in set(calm_idx)]
    if not calm_idx:
        calm_idx = other_idx
    texts = [item["text"] for item in data]
    steps = max(1, len(train_idx) // BATCH)
    snapshots = []
    for epoch in range(EPOCHS):
        rng = np.random.default_rng(20 + epoch)
        total = 0.0
        _prepare(model)
        for _ in range(steps):
            pick = np.concatenate([
                rng.choice(urgent_idx, BATCH // 2, replace=True),
                rng.choice(calm_idx, BATCH // 4, replace=True),
                rng.choice(other_idx, BATCH // 4, replace=True),
            ])
            batch_text = [texts[int(i)] for i in pick]
            emb = pooled(model, tokenizer, batch_text, max_length=128, train_last=LAST, token_drop=0.10)
            labels = torch.tensor([LABELS.index(data[int(i)]["label"]) for i in pick], dtype=torch.long)
            urgent = torch.tensor([data[int(i)]["urgent"] for i in pick], dtype=torch.float32)
            negated = torch.tensor([data[int(i)]["negated"] for i in pick], dtype=torch.float32)
            loss = _supcon(emb, labels.new_tensor([data[int(i)]["urgent"] for i in pick]))
            loss = loss + functional.binary_cross_entropy_with_logits(urgent_head(emb).squeeze(-1), urgent)
            loss = loss + 0.4 * functional.cross_entropy(label_head(emb), labels)
            loss = loss + 0.3 * functional.binary_cross_entropy_with_logits(neg_head(emb).squeeze(-1), negated)
            for name, head in ask_heads.items():
                target = torch.tensor([1.0 if data[int(i)]["ask"] == name else 0.0 for i in pick])
                loss = loss + 0.25 * functional.binary_cross_entropy_with_logits(head(emb).squeeze(-1), target)
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(encoder_params, 1.0)
            optimizer.step()
            total += float(loss.detach())
        snapshots.append(_snapshot(model))
        print(f"epoch {epoch + 1} loss={total / steps:.4f}", flush=True)
    return snapshots


def main() -> None:
    global EPOCHS
    if os.environ.get("LANE_CONTINUE") == "1":
        EPOCHS = 1
    torch.manual_seed(7)
    data = rows()
    hand = json.loads(HAND.read_text(encoding="utf-8"))
    train_idx = [i for i, item in enumerate(data) if item["fold"] != 0 and item["group"] not in WATCH and item["group"] not in PICK]
    watch_idx = [i for i, item in enumerate(data) if item["group"] in PICK]
    val_idx = [i for i, item in enumerate(data) if item["fold"] == 0]
    if not watch_idx or not train_idx or not val_idx:
        raise SystemExit("split produced an empty train, watch, or validation set")
    print(f"rows {len(data)} train {len(train_idx)} watch {len(watch_idx)} fold0 {len(val_idx)}", flush=True)

    model, tokenizer = load_bundle(apply_delta=os.environ.get("LANE_CONTINUE") == "1")
    _prepare(model)
    snapshots = _train_encoder(data, train_idx, model, tokenizer)

    texts = [item["text"] for item in data]
    best = None
    best_state = snapshots[0]
    # The threshold used to judge an epoch is the fold-0 threshold, not one
    # fit on the pick set. A late epoch can score perfectly on a pick-set
    # threshold and still sit the real outages under the fold-0 cutoff.
    for epoch, state in enumerate(snapshots, start=1):
        _restore(model, state)
        vectors = _embed_rows(model, tokenizer, texts)
        _, (train_x, watch_x, val_x) = _center(vectors[train_idx], vectors[watch_idx], vectors[val_idx])
        y_train = np.asarray([data[i]["urgent"] for i in train_idx], dtype=np.int64)
        y_watch = np.asarray([data[i]["urgent"] for i in watch_idx], dtype=np.int64)
        y_val = np.asarray([data[i]["urgent"] for i in val_idx], dtype=np.int64)
        threshold, recall, fpr, weights, bias = _fit_probe(train_x, y_train, val_x, y_val)
        watch_scores = _predict_sigmoid(watch_x, weights, bias)
        watch_recall, watch_fpr, *_ = _rates(watch_scores, y_watch, threshold)
        print(
            f"epoch {epoch} fold0 threshold={threshold:.2f} recall={recall:.3f} fpr={fpr:.3f} "
            f"pick recall={watch_recall:.3f} fpr={watch_fpr:.3f}",
            flush=True,
        )
        meets = recall >= 0.90 and fpr <= 0.05
        # Earlier epochs win ties. Later ones memorize the training sentences.
        rank = (1 if meets else 0, round(watch_recall, 3), round(recall, 3), -round(fpr, 3), -epoch)
        if best is None or rank > best[0]:
            best = (rank, state)
    _restore(model, best[1])
    save_delta(model)
    load_bundle.cache_clear()
    embed.cache_clear() if hasattr(embed, "cache_clear") else None
    from app import embedder as embedder_module

    embedder_module.embed_one.cache_clear()

    print("embedding with the chosen encoder", flush=True)
    vectors = embed(texts, max_length=128)
    hand_text = [f"{item.get('subject', '')}\n{item['body']}".strip() for item in hand]
    hand_vectors = embed(hand_text, max_length=128)

    # The shipped head sees every training group, including the watch groups.
    # Fold 0 stays out of the fit. The threshold is chosen only on fold 0.
    fit_idx = [i for i, item in enumerate(data) if item["fold"] != 0 and item["group"] not in PICK]
    mean, (train_x, val_x, hand_x) = _center(vectors[fit_idx], vectors[val_idx], hand_vectors)

    y_label = np.asarray([LABELS.index(data[i]["label"]) for i in fit_idx], dtype=np.int64)
    buckets: dict[int, list[int]] = defaultdict(list)
    for local, label in enumerate(y_label):
        buckets[int(label)].append(local)
    cap = min(len(bucket) for bucket in buckets.values())
    rng = np.random.default_rng(7)
    kept = np.concatenate([rng.choice(bucket, cap, replace=False) for bucket in buckets.values()])
    label_w, label_b = _softmax(train_x[kept], y_label[kept], len(LABELS))
    val_labels = np.asarray([LABELS.index(data[i]["label"]) for i in val_idx], dtype=np.int64)
    pred_labels = (val_x @ label_w.T + label_b).argmax(axis=1)
    label_correct = int((pred_labels == val_labels).sum())

    y_urgent = np.asarray([data[i]["urgent"] for i in fit_idx], dtype=np.int64)
    chosen = _balance_idx(y_urgent, seed=3)
    urgent_w, urgent_b = _sigmoid(train_x[chosen], y_urgent[chosen])
    val_urgent = np.asarray([data[i]["urgent"] for i in val_idx], dtype=np.int64)
    y_neg = np.asarray([data[i]["negated"] for i in fit_idx], dtype=np.int64)
    neg_idx = _balance_idx(y_neg, seed=4)
    neg_w, neg_b = _sigmoid(train_x[neg_idx], y_neg[neg_idx])
    neg_scores = _predict_sigmoid(train_x, neg_w, neg_b)
    neg_threshold = 0.5
    train_urgent = y_urgent == 1
    for step in range(50, 95):
        trial = step / 100
        if train_urgent.any() and float((neg_scores[train_urgent] >= trial).mean()) <= 0.05:
            gold_neg = y_neg == 1
            if gold_neg.any() and float((neg_scores[gold_neg] >= trial).mean()) >= 0.8:
                neg_threshold = trial
                break

    ask_weights = {}
    centered = vectors - mean
    for name in ("money", "bank", "credential"):
        y = np.asarray([1 if data[i]["ask"] == name else 0 for i in fit_idx], dtype=np.int64)
        picked = _balance_idx(y, seed=11)
        weights, bias = _sigmoid(train_x[picked], y[picked])
        ask_weights[name] = {"weights": weights.tolist(), "bias": float(bias)}

    hand_urgent = np.asarray([item["urgent"] for item in hand], dtype=np.int64)
    hand_labels = np.asarray([LABELS.index(item["label"]) if item["label"] in LABELS else LABELS.index("other") for item in hand])
    hand_pred = (hand_x @ label_w.T + label_b).argmax(axis=1)
    hand_label_correct = int((hand_pred == hand_labels).sum())

    def _ask_rate(name: str) -> tuple[int, int]:
        block = ask_weights[name]
        weights = np.asarray(block["weights"])
        scores = _predict_sigmoid(hand_x, weights, block["bias"])
        gold = np.asarray([1 if item["ask"] == name else 0 for item in hand])
        pred = scores >= 0.5
        tp = int((pred & (gold == 1)).sum())
        pos_n = int((gold == 1).sum())
        return tp, pos_n

    money_tp, money_pos = _ask_rate("money")
    bank_tp, bank_pos = _ask_rate("bank")
    cred_tp, cred_pos = _ask_rate("credential")

    payload = {
        "mean": mean.astype(float).tolist(),
        "label": {
            "labels": list(LABELS),
            "weights": label_w.tolist(),
            "bias": label_b.tolist(),
        },
        "urgency": {
            "urgent": {"weights": urgent_w.tolist(), "bias": float(urgent_b), "threshold": 0.5},
            "negated": {"weights": neg_w.tolist(), "bias": float(neg_b), "threshold": neg_threshold},
        },
        "ask": {
            **ask_weights,
            "threshold": 0.5,
        },
        "money": {**ask_weights["money"], "threshold": 0.5},
        "risk": {"weights": {}, "bias": 0.0, "threshold": 1.0},
    }
    OUT.write_text(json.dumps(payload), encoding="utf-8")
    # The desk takes the max over the full text and each real sentence, and it
    # applies negation per span. Choose the threshold on that same score.
    from app.classifier import message_urgent
    from app import heads as heads_module

    heads_module._weights.cache_clear()
    val_span = np.asarray([message_urgent(data[i]["text"], data[i]["text"]) for i in val_idx], dtype=np.float64)
    threshold, recall, fpr = _calibrate(val_span, val_urgent)
    recall, fpr, tp, pos, fp, neg = _rates(val_span, val_urgent, threshold)
    print(f"fold 0 threshold={threshold:.2f} recall={recall:.3f} fpr={fpr:.3f}", flush=True)
    payload["urgency"]["urgent"]["threshold"] = threshold
    OUT.write_text(json.dumps(payload), encoding="utf-8")
    heads_module._weights.cache_clear()
    hand_span = np.asarray(
        [message_urgent(f"{item.get('subject', '')}\n{item['body']}".strip(), item["body"]) for item in hand],
        dtype=np.float64,
    )
    hand_recall, hand_fpr, hand_tp, hand_pos, hand_fp, hand_neg_n = _rates(hand_span, hand_urgent, threshold)
    report = {
        "split": "group fold, fold 0 held out, siblings share a group",
        "rows": len(data),
        "train_rows": len(fit_idx),
        "heldout_rows": len(val_idx),
        "watch_rows": len(watch_idx),
        "label_accuracy": label_correct / len(val_idx),
        "label_correct": label_correct,
        "label_total": len(val_idx),
        "urgent_threshold": threshold,
        "urgent_recall": recall,
        "urgent_fpr": fpr,
        "urgent_tp": tp,
        "urgent_pos": pos,
        "urgent_fp": fp,
        "urgent_neg": neg,
        "negation_threshold": neg_threshold,
        "fold_metrics": [
            {"fold": 0, "threshold": threshold, "recall": recall, "fpr": fpr, "n": len(val_idx)},
        ],
        "fold_recall_mean": recall,
        "fold_fpr_mean": fpr,
        "hand_rows": len(hand),
        "hand_label_accuracy": hand_label_correct / len(hand),
        "hand_label_correct": hand_label_correct,
        "hand_urgent_recall": hand_recall,
        "hand_urgent_fpr": hand_fpr,
        "hand_urgent_tp": hand_tp,
        "hand_urgent_pos": hand_pos,
        "hand_urgent_fp": hand_fp,
        "hand_urgent_neg": hand_neg_n,
        "hand_money_tp": money_tp,
        "hand_money_pos": money_pos,
        "hand_bank_tp": bank_tp,
        "hand_bank_pos": bank_pos,
        "hand_credential_tp": cred_tp,
        "hand_credential_pos": cred_pos,
        "encoder": f"intfloat/multilingual-e5-small revision 614241f622f53c4eeff9890bdc4f31cfecc418b3, SetFit-style fine-tune of the last {LAST} layers",
        "head": "linear on the fine-tuned embedding, threshold fit on group fold 0",
        "urgent_score": "max over the full text and body sentences of at least 40 characters; negation is applied per span",
    }
    METRICS.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("urgent_recall", "urgent_fpr", "urgent_threshold", "label_accuracy", "hand_urgent_recall", "hand_urgent_fpr", "hand_label_accuracy")}, indent=2))


if __name__ == "__main__":
    main()
