"""
weighter.py — Applies source weights to produce a balanced, weighted corpus.

Strategies:
  upsample   — repeat high-weight docs (fractional weights → probabilistic)
  downsample — skip low-weight docs with probability (1 - weight)
  both       — downsample docs with weight < 1.0, upsample docs with weight > 1.0

Output is a JSONL stream where each doc appears N times according to its weight.
The shard writer consumes this stream; order is shuffled before sharding.
"""

from __future__ import annotations

import json
import logging
import math
import random
from pathlib import Path
from typing import Iterator

import yaml

from pipeline.types import Document

log = logging.getLogger("weighter")


class DomainWeighter:

    def __init__(self, config_path: str | Path, strategy: str = "upsample"):
        with open(config_path) as f:
            self._cfg = yaml.safe_load(f)
        # strategy comes from pipeline_config.yaml weight.strategy, not source_weights.yaml.
        # Accept it as a constructor argument so the orchestrator can pass it through.
        self._strategy = strategy
        self.stats = {
            "docs_in":  0,
            "docs_out": 0,
            "total_weight": 0.0,
        }

    def _repeat_count(self, weight: float) -> tuple[int, float]:
        """
        Return (whole_repeats, fractional_prob).
        e.g. weight=2.7 → (2, 0.7): emit doc twice always, third time w/ prob 0.7.
        weight=0.4  → (0, 0.4): emit doc once w/ prob 0.4.
        """
        whole = math.floor(weight)
        frac  = weight - whole
        return whole, frac

    def apply(self, docs: Iterator[Document]) -> Iterator[Document]:
        strategy = self._strategy

        for doc in docs:
            self.stats["docs_in"] += 1
            w = max(doc.final_weight, 0.0)
            self.stats["total_weight"] += w

            if strategy == "upsample":
                whole, frac = self._repeat_count(w)
                for _ in range(whole):
                    self.stats["docs_out"] += 1
                    yield doc
                if frac > 0 and random.random() < frac:
                    self.stats["docs_out"] += 1
                    yield doc

            elif strategy == "downsample":
                # Weights > 1.0 are kept always; < 1.0 are probabilistic
                if w >= 1.0 or random.random() < w:
                    self.stats["docs_out"] += 1
                    yield doc

            elif strategy == "both":
                if w < 1.0:
                    if random.random() < w:
                        self.stats["docs_out"] += 1
                        yield doc
                else:
                    whole, frac = self._repeat_count(w)
                    for _ in range(whole):
                        self.stats["docs_out"] += 1
                        yield doc
                    if frac > 0 and random.random() < frac:
                        self.stats["docs_out"] += 1
                        yield doc

    def print_stats(self):
        s = self.stats
        log.info(
            f"Weighter | docs_in={s['docs_in']} docs_out={s['docs_out']} "
            f"avg_weight={s['total_weight']/max(s['docs_in'],1):.3f} "
            f"expansion={s['docs_out']/max(s['docs_in'],1):.2f}x"
        )


# ── Content-type re-classifier (applied after crawl to fix any unknowns) ────

_CONTENT_TYPE_KEYWORDS: list[tuple[list[str], str]] = [
    (["abstract", "introduction", "methodology", "conclusion", "references", "theorem", "lemma"], "research_paper"),
    (["def ", "class ", "fn ", "impl ", "function ", "#include", "import ", "from . import"], "source_code"),
    (["parameters", "returns", "example usage", "api reference", "install", "pip install"], "technical_doc"),
    (["dataset", "benchmark", "experiment", "evaluation", "accuracy", "f1 score"], "research_paper"),
    (["chapter ", "section ", "textbook", "exercise ", "problem set"], "textbook"),
    (["press release", "breaking news", "reported", "journalist"], "news_article"),
]

def reclassify_content_type(doc: Document) -> str:
    if doc.content_type not in ("unknown", ""):
        return doc.content_type
    text_lower = doc.text.lower()
    for keywords, ctype in _CONTENT_TYPE_KEYWORDS:
        hits = sum(1 for kw in keywords if kw in text_lower)
        if hits >= 2:
            return ctype
    return "unknown"
