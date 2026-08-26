"""
shard_writer.py — Tokenizes the weighted corpus and writes binary training shards.

Output format: numpy uint16 (or uint32) arrays, one file per shard.
  shard_00000_train.bin, shard_00001_train.bin, ..., shard_00042_val.bin

Each shard is a flat array of token IDs.
The training loop reads these via np.memmap for zero-copy streaming.

Layout: [tok0, tok1, tok2, ..., tokN]
        sequences are packed back-to-back with EOS between documents.

Compatible with nanoGPT-style data loaders.
"""

from __future__ import annotations

import json
import logging
import random
import struct
import os
import tempfile
from pathlib import Path
from typing import Iterator

import numpy as np

log = logging.getLogger("shard_writer")


class ShardWriter:

    def __init__(self, cfg: dict, tokenizer):
        self._cfg     = cfg
        self._tok     = tokenizer
        self._seq_len = cfg.get("sequence_length", 1024)
        self._dtype   = np.uint16 if cfg.get("dtype", "uint16") == "uint16" else np.uint32
        self._shard_size = cfg.get("shard_size_tokens", 10_000_000)
        self._out_dir    = Path(cfg.get("output_dir", "output/shards"))
        self._val_frac   = cfg.get("val_fraction", 0.005)
        self._shuffle    = cfg.get("shuffle_docs", True)
        self._seed       = int(cfg.get("seed", 42))
        self._out_dir.mkdir(parents=True, exist_ok=True)

        # Get EOS token id
        vocab = self._tok.get_vocab()
        self._vocab_size = len(vocab)
        max_id = np.iinfo(self._dtype).max
        if self._vocab_size - 1 > max_id:
            raise ValueError(f"Tokenizer vocab {self._vocab_size} exceeds {self._dtype.__name__} capacity {max_id + 1}")
        self._eos_id = vocab.get("<|eos|>", vocab.get("</s>", 2))
        log.info(f"ShardWriter | seq_len={self._seq_len} shard={self._shard_size} "
                 f"dtype={self._dtype.__name__} eos={self._eos_id}")

        self.stats = {
            "docs_processed": 0,
            "total_tokens":   0,
            "shards_written": 0,
            "train_shards":   0,
            "val_shards":     0,
        }

    def _tokenize_doc(self, text: str) -> list[int]:
        enc = self._tok.encode(text)
        ids = enc.ids
        if not ids:
            return []
        # Append EOS between documents
        ids.append(self._eos_id)
        return ids

    def _write_shard(self, tokens: list[int], shard_idx: int, split: str):
        arr  = np.asarray(tokens)
        max_id = np.iinfo(self._dtype).max
        if arr.size and (int(arr.min()) < 0 or int(arr.max()) > max_id):
            raise ValueError(f"Token id out of range for {self._dtype.__name__}: min={arr.min()} max={arr.max()}")
        arr = arr.astype(self._dtype, copy=False)
        name = f"shard_{shard_idx:05d}_{split}.bin"
        path = self._out_dir / name
        fd, tmp = tempfile.mkstemp(prefix=name + ".", suffix=".tmp", dir=self._out_dir)
        try:
            with os.fdopen(fd, "wb") as f:
                arr.tofile(f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except Exception:
            try: os.unlink(tmp)
            except OSError: pass
            raise
        size_mb = arr.nbytes / 1024 / 1024
        log.info(f"Wrote {path} | tokens={len(tokens):,} size={size_mb:.1f}MB")
        self.stats["shards_written"] += 1
        if split == "train":
            self.stats["train_shards"] += 1
        else:
            self.stats["val_shards"]   += 1

    def write(self, jsonl_path: str | Path) -> None:
        """
        Read weighted JSONL corpus, tokenize, pack into shards.
        Shuffles document order before packing if shuffle_docs=true.
        """
        jsonl_path = Path(jsonl_path)
        log.info(f"Reading corpus from {jsonl_path} ...")

        # Load all doc texts (we need them in memory to shuffle)
        doc_texts: list[str] = []
        bad = 0
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    text = obj.get("text", "")
                    if text:
                        doc_texts.append(text)
                except json.JSONDecodeError as exc:
                    bad += 1
                    log.error(f"Malformed shard input {jsonl_path}: {exc}")
                    raise RuntimeError(f"Shard input integrity failure: malformed JSON in {jsonl_path}") from exc

        if not doc_texts:
            raise RuntimeError(f"Shard input contains no usable text: {jsonl_path}")
        log.info(f"Loaded {len(doc_texts):,} docs")

        if self._shuffle:
            random.Random(self._seed).shuffle(doc_texts)
            log.info("Docs shuffled")

        # Split into train / val
        n_val   = max(1, int(len(doc_texts) * self._val_frac))
        val_docs = doc_texts[:n_val]
        trn_docs = doc_texts[n_val:]
        log.info(f"Train docs={len(trn_docs):,} val docs={len(val_docs):,}")

        for split, docs in [("train", trn_docs), ("val", val_docs)]:
            shard_buf: list[int] = []
            shard_idx = 0

            for text in docs:
                ids = self._tokenize_doc(text)
                if not ids:
                    continue
                shard_buf.extend(ids)
                self.stats["docs_processed"] += 1
                self.stats["total_tokens"]   += len(ids)

                while len(shard_buf) >= self._shard_size:
                    self._write_shard(shard_buf[:self._shard_size], shard_idx, split)
                    shard_buf  = shard_buf[self._shard_size:]
                    shard_idx += 1

            # Flush remainder
            if shard_buf:
                self._write_shard(shard_buf, shard_idx, split)

        self.print_stats()

    def print_stats(self):
        s = self.stats
        log.info(
            f"ShardWriter | docs={s['docs_processed']:,} tokens={s['total_tokens']:,} "
            f"shards={s['shards_written']} (train={s['train_shards']} val={s['val_shards']})"
        )


# ── DataLoader helper for nanoGPT-style training ────────────────────────────

class ShardDataLoader:
    """
    Memory-mapped loader for .bin shards.
    Compatible with nanoGPT's data loading pattern.

    Usage:
        loader = ShardDataLoader("output/shards", split="train", seq_len=1024)
        x, y = loader.next_batch(batch_size=8)
    """

    def __init__(self, shard_dir: str | Path, split: str, seq_len: int,
                 dtype=np.uint16, seed: int = 42):
        self._dir     = Path(shard_dir)
        self._split   = split
        self._seq_len = seq_len
        self._dtype   = dtype
        self._rng     = random.Random(seed)

        self._shards  = sorted(self._dir.glob(f"shard_*_{split}.bin"))
        if not self._shards:
            raise FileNotFoundError(f"No {split} shards in {shard_dir}")

        log.info(f"ShardDataLoader: {len(self._shards)} {split} shards in {shard_dir}")
        self._rng.shuffle(self._shards)
        self._shard_idx = 0
        self._pos       = 0
        self._data      = self._load_shard(self._shards[0])

    def _load_shard(self, path: Path) -> np.ndarray:
        arr = np.memmap(path, dtype=self._dtype, mode="r")
        return arr

    def next_batch(self, batch_size: int) -> tuple[np.ndarray, np.ndarray]:
        """Returns (x, y) arrays of shape (batch_size, seq_len)."""
        import torch
        L = self._seq_len + 1
        x_list, y_list = [], []

        for _ in range(batch_size):
            # Advance shard if needed. Refuse undersized corpora instead of
            # looping forever when every shard is shorter than seq_len+1.
            attempts = 0
            while self._pos + L >= len(self._data):
                self._shard_idx = (self._shard_idx + 1) % len(self._shards)
                self._data = self._load_shard(self._shards[self._shard_idx])
                self._pos  = 0
                attempts += 1
                if attempts > len(self._shards):
                    raise RuntimeError(f"No {self._split} shard contains at least {L} tokens; increase corpus/shard size or reduce seq_len")
                if self._shard_idx == 0:
                    self._rng.shuffle(self._shards)

            chunk = self._data[self._pos: self._pos + L].astype(np.int64)
            x_list.append(chunk[:-1])
            y_list.append(chunk[1:])
            self._pos += self._seq_len

        x = torch.from_numpy(np.stack(x_list))
        y = torch.from_numpy(np.stack(y_list))
        return x, y
