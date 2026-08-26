"""
train_tokenizer.py — Trains a BPE tokenizer on the cleaned corpus.

Uses HuggingFace `tokenizers` (Rust-backed, fast).
Output is a directory compatible with transformers.AutoTokenizer
and also with llama.cpp's convert scripts.

Special tokens match the Llama-2 convention so the GGUF output
will work with Ollama out of the box.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Iterator

from pipeline.types import Document

log = logging.getLogger("tokenizer")

try:
    from tokenizers import Tokenizer, decoders, pre_tokenizers, trainers
    from tokenizers.models import BPE
    from tokenizers.normalizers import NFKC, Sequence as NormSequence
    from tokenizers.pre_tokenizers import ByteLevel
    from tokenizers.trainers import BpeTrainer
    HF_TOKENIZERS_AVAILABLE = True
except ImportError:
    HF_TOKENIZERS_AVAILABLE = False
    log.warning("tokenizers library not installed")


def _doc_stream(jsonl_path: Path, sample_size: int | None, seed: int = 42) -> Iterator[str]:
    """Yield text strings from a JSONL file, optionally sampling."""
    lines = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                lines.append(line)

    if sample_size is not None and len(lines) > sample_size:
        rng = random.Random(seed)
        lines = rng.sample(lines, sample_size)
        log.info(f"Tokenizer training: sampled {sample_size} / {len(lines)+sample_size} docs")

    for line in lines:
        try:
            obj = json.loads(line)
            text = obj.get("text", "")
            if text:
                yield text
        except json.JSONDecodeError:
            continue


class BPETokenizerTrainer:

    def __init__(self, cfg: dict):
        self._cfg         = cfg
        self._vocab_size  = cfg.get("vocab_size", 32000)
        self._min_freq    = cfg.get("min_frequency", 2)
        self._special     = cfg.get("special_tokens", [
            "<|pad|>", "<|unk|>", "<|bos|>", "<|eos|>", "<|sep|>", "<|mask|>"
        ])
        self._output_path = Path(cfg.get("output_path", "output/tokenizer"))
        self._sample_size = cfg.get("sample_size", 500_000) if cfg.get("train_on_sample") else None

    def train(self, corpus_path: str | Path) -> None:
        if not HF_TOKENIZERS_AVAILABLE:
            raise RuntimeError("tokenizers library not installed; run: pip install tokenizers")

        corpus_path = Path(corpus_path)
        self._output_path.mkdir(parents=True, exist_ok=True)

        log.info(f"Training BPE tokenizer | vocab={self._vocab_size} "
                 f"min_freq={self._min_freq} sample={self._sample_size}")

        tokenizer = Tokenizer(BPE(unk_token="<|unk|>"))

        # Normalizer: NFKC unicode normalisation
        tokenizer.normalizer = NormSequence([NFKC()])

        # Pre-tokenizer: ByteLevel (same as GPT-2 / Llama)
        tokenizer.pre_tokenizer = ByteLevel(add_prefix_space=False)

        # Decoder
        tokenizer.decoder = decoders.ByteLevel()

        trainer = BpeTrainer(
            vocab_size      = self._vocab_size,
            min_frequency   = self._min_freq,
            special_tokens  = self._special,
            show_progress   = True,
        )

        # Write corpus to a temp file for the trainer
        tmp_path = self._output_path / "_train_corpus.txt"
        log.info(f"Writing training corpus to {tmp_path} ...")
        count = 0
        with open(tmp_path, "w", encoding="utf-8") as f:
            for text in _doc_stream(corpus_path, self._sample_size):
                f.write(text.replace("\n", " ") + "\n")
                count += 1
                if count % 50_000 == 0:
                    log.info(f"  ... {count} docs written")

        log.info(f"Training on {count} docs ...")
        tokenizer.train([str(tmp_path)], trainer)

        # Save tokenizer
        out_json = self._output_path / "tokenizer.json"
        tokenizer.save(str(out_json))
        log.info(f"Tokenizer saved to {out_json}")

        # Write tokenizer_config.json (HF-compatible)
        config = {
            "bos_token":     "<|bos|>",
            "eos_token":     "<|eos|>",
            "unk_token":     "<|unk|>",
            "pad_token":     "<|pad|>",
            "model_type":    "llama",
            "tokenizer_class": "PreTrainedTokenizerFast",
            "vocab_size":    self._vocab_size,
        }
        with open(self._output_path / "tokenizer_config.json", "w") as f:
            json.dump(config, f, indent=2)

        # Write special_tokens_map.json
        spm = {
            "bos_token": "<|bos|>",
            "eos_token": "<|eos|>",
            "unk_token": "<|unk|>",
            "pad_token": "<|pad|>",
        }
        with open(self._output_path / "special_tokens_map.json", "w") as f:
            json.dump(spm, f, indent=2)

        # Clean up temp corpus
        tmp_path.unlink(missing_ok=True)
        log.info("Tokenizer training complete")
        return tokenizer

    def encode(self, text: str, tokenizer=None) -> list[int]:
        if tokenizer is None:
            raise ValueError("Pass a trained tokenizer instance")
        return tokenizer.encode(text).ids

    def load(self) -> "Tokenizer":
        if not HF_TOKENIZERS_AVAILABLE:
            raise RuntimeError("tokenizers library not installed")
        tok_path = self._output_path / "tokenizer.json"
        if not tok_path.exists():
            raise FileNotFoundError(f"No tokenizer at {tok_path}; run train() first")
        from tokenizers import Tokenizer as T
        tok = T.from_file(str(tok_path))
        log.info(f"Loaded tokenizer from {tok_path} (vocab={tok.get_vocab_size()})")
        return tok
