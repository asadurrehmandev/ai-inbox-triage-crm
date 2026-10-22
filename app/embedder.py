"""Local multilingual embeddings.

The base weights are intfloat/multilingual-e5-small, revision
614241f622f53c4eeff9890bdc4f31cfecc418b3. The first call downloads that
revision and checks the sha256 of each file. A SetFit-style fine-tune of the
upper encoder layers is stored in ``encoder_delta.npz`` and applied on top of
those frozen base weights. Nothing is sent to a paid model. Each text is
prefixed with ``query: `` because that is how this model was trained.
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
from functools import lru_cache
from pathlib import Path

import numpy as np

_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
_REPO = "https://huggingface.co/intfloat/multilingual-e5-small/resolve/" + _REVISION
_FILES = {
    "config.json": "69137736cab8b8903a07fe8afaafdda25aac55415a12a55d1bffa9f581abf959",
    "model.safetensors": "1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477",
    "tokenizer.json": "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
    "tokenizer_config.json": "a1d6bc8734a6f635dc158508bef000f8e2e5a759c7d92f984b2c86e5ff53425b",
    "special_tokens_map.json": "d05497f1da52c5e09554c0cd874037a083e1dc1b9cfd48034d1c717f1afc07a7",
    "sentencepiece.bpe.model": "cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865",
}
DELTA = Path(__file__).resolve().parent / "encoder_delta.npz"
# Training updates this many upper layers (scripts/train_heads.py LAST).
# The delta must store every one of them or inference drops the lower tuned layers.
_TUNED_LAYERS = 8


def cache_dir() -> Path:
    override = os.environ.get("LANE_MODEL_DIR", "").strip()
    path = Path(override) if override else Path.home() / ".cache" / "lane" / "e5"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_model() -> Path:
    folder = cache_dir()
    for name, expected in _FILES.items():
        target = folder / name
        if target.exists() and target.stat().st_size > 0 and _sha256(target) == expected:
            continue
        tmp = target.with_suffix(target.suffix + ".part")
        urllib.request.urlretrieve(f"{_REPO}/{name}", tmp)
        actual = _sha256(tmp)
        if actual != expected:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"{name} sha256 {actual} did not match the pinned revision {_REVISION}")
        tmp.replace(target)
    return folder


def _apply_delta(model, path: Path) -> None:
    import torch

    blob = np.load(path)
    params = dict(model.named_parameters())
    with torch.no_grad():
        for key in blob.files:
            if key not in params:
                raise RuntimeError(f"encoder delta has an unknown parameter {key}")
            value = torch.from_numpy(np.asarray(blob[key], dtype=np.float32))
            params[key].copy_(value)


@lru_cache(maxsize=1)
def load_bundle(apply_delta: bool = True):
    """Base encoder, tokenizer, and the fine-tune delta when it is present."""
    import torch
    from transformers import AutoModel, AutoTokenizer

    torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
    folder = ensure_model()
    tokenizer = AutoTokenizer.from_pretrained(folder, local_files_only=True)
    model = AutoModel.from_pretrained(folder, local_files_only=True)
    model.eval()
    if apply_delta and DELTA.exists():
        _apply_delta(model, DELTA)
    return model, tokenizer


def save_delta(model, path: Path | None = None) -> Path:
    """Write the upper encoder layers. The base download stays pinned."""
    target = path or DELTA
    arrays = {}
    start = model.config.num_hidden_layers - _TUNED_LAYERS
    for name, param in model.named_parameters():
        if not name.startswith("encoder.layer."):
            continue
        layer = int(name.split(".")[2])
        if layer < start:
            continue
        arrays[name] = param.detach().cpu().numpy().astype(np.float32)
    if not arrays:
        raise RuntimeError("no encoder layers were marked for the delta")
    np.savez_compressed(target, **arrays)
    return target


def _tokenize(tokenizer, texts: list[str], max_length: int):
    prefixed = ["query: " + (text or " ").replace("\n", " ")[:4000] for text in texts]
    encoded = tokenizer(
        prefixed,
        padding=True,
        truncation=True,
        max_length=max_length,
        return_tensors="pt",
    )
    return encoded


def pooled(model, tokenizer, texts: list[str], max_length: int = 128, train_last: int = 0, token_drop: float = 0.0):
    """Mean-pooled, L2-normalized embeddings.

    ``train_last`` keeps the first layers frozen and differentiable only
    through the upper layers, which is the fine-tune used at training time.
    """
    import torch
    import torch.nn.functional as functional

    if not texts:
        return torch.zeros((0, model.config.hidden_size))
    batch = _tokenize(tokenizer, texts, max_length)
    if token_drop > 0 and train_last > 0:
        # Hide a few content tokens so the update cannot memorize a whole sentence.
        ids = batch["input_ids"]
        mask = batch["attention_mask"]
        drop = torch.rand(ids.shape) < token_drop
        special = torch.zeros_like(ids, dtype=torch.bool)
        for token_id in (
            tokenizer.pad_token_id,
            getattr(tokenizer, "cls_token_id", None),
            getattr(tokenizer, "sep_token_id", None),
            getattr(tokenizer, "bos_token_id", None),
            getattr(tokenizer, "eos_token_id", None),
        ):
            if token_id is not None:
                special |= ids.eq(token_id)
        drop &= ~special & mask.bool()
        batch["attention_mask"] = mask.masked_fill(drop, 0)
    if train_last <= 0:
        with torch.no_grad():
            hidden = model(**batch).last_hidden_state
    else:
        start = model.config.num_hidden_layers - train_last
        hidden = model.embeddings(input_ids=batch["input_ids"])
        extended = model.get_extended_attention_mask(batch["attention_mask"], batch["input_ids"].shape)
        with torch.no_grad():
            for layer in model.encoder.layer[:start]:
                hidden = layer(hidden, attention_mask=extended)[0]
        hidden = hidden.detach()
        for layer in model.encoder.layer[start:]:
            hidden = layer(hidden, attention_mask=extended)[0]
    mask = batch["attention_mask"].unsqueeze(-1).to(hidden.dtype)
    summed = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-6)
    return functional.normalize(summed, dim=1)


def embed(texts: list[str], max_length: int = 256) -> np.ndarray:
    """L2-normalized mean-pooled embeddings. Shape ``(n, 384)``."""
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    model, tokenizer = load_bundle(apply_delta=True)
    rows = []
    for start in range(0, len(texts), 16):
        chunk = pooled(model, tokenizer, texts[start : start + 16], max_length=max_length, train_last=0)
        rows.append(chunk.detach().cpu().numpy().astype(np.float32))
    return np.concatenate(rows, axis=0)


@lru_cache(maxsize=512)
def embed_one(text: str) -> tuple[float, ...]:
    row = embed([text or ""])[0]
    return tuple(float(value) for value in row)
