"""Local multilingual embeddings.

The weights are intfloat/multilingual-e5-small, loaded as the quantized ONNX
build (about 130 MB with the tokenizer). The first call downloads them into
the user cache. Nothing is sent to a paid model. Each text is prefixed with
``query: `` because that is how this model was trained.
"""

from __future__ import annotations

import os
import urllib.request
from functools import lru_cache
from pathlib import Path

import numpy as np

_FILES = {
    "model_quantized.onnx": "https://huggingface.co/Xenova/multilingual-e5-small/resolve/main/onnx/model_quantized.onnx",
    "tokenizer.json": "https://huggingface.co/Xenova/multilingual-e5-small/resolve/main/tokenizer.json",
}


def cache_dir() -> Path:
    override = os.environ.get("LANE_MODEL_DIR", "").strip()
    path = Path(override) if override else Path.home() / ".cache" / "lane" / "e5"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_model() -> Path:
    folder = cache_dir()
    for name, url in _FILES.items():
        target = folder / name
        if target.exists() and target.stat().st_size > 0:
            continue
        tmp = target.with_suffix(target.suffix + ".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(target)
    return folder


@lru_cache(maxsize=1)
def _session():
    import onnxruntime as ort
    from tokenizers import Tokenizer

    folder = ensure_model()
    tokenizer = Tokenizer.from_file(str(folder / "tokenizer.json"))
    options = ort.SessionOptions()
    # One thread keeps the pooling reduction stable from run to run.
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(
        str(folder / "model_quantized.onnx"),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )
    return session, tokenizer


def _prepare(tokenizer, texts: list[str], max_length: int):
    tokenizer.enable_truncation(max_length=max_length)
    tokenizer.enable_padding(pad_id=1, pad_token="<pad>")
    encoded = tokenizer.encode_batch(["query: " + (text or " ").replace("\n", " ")[:4000] for text in texts])
    ids = np.asarray([item.ids for item in encoded], dtype=np.int64)
    mask = np.asarray([item.attention_mask for item in encoded], dtype=np.int64)
    types = np.zeros_like(ids)
    return ids, mask, types


def embed(texts: list[str], max_length: int = 256) -> np.ndarray:
    """L2-normalized mean-pooled embeddings. Shape ``(n, 384)``."""
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    session, tokenizer = _session()
    ids, mask, types = _prepare(tokenizer, texts, max_length)
    hidden = session.run(
        None,
        {"input_ids": ids, "attention_mask": mask, "token_type_ids": types},
    )[0]
    weights = mask.astype(np.float32)[..., None]
    pooled = (hidden * weights).sum(axis=1) / np.maximum(weights.sum(axis=1), 1.0)
    norms = np.linalg.norm(pooled, axis=1, keepdims=True)
    return (pooled / np.maximum(norms, 1e-9)).astype(np.float32)


@lru_cache(maxsize=512)
def embed_one(text: str) -> tuple[float, ...]:
    row = embed([text or ""])[0]
    return tuple(float(value) for value in row)
