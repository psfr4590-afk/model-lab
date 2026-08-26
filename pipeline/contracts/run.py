"""
Shared data types for the pretrain pipeline.
Every stage consumes and/or produces Documents.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Document:
    """Central data unit flowing through the pipeline."""

    # Identity
    doc_id:   str
    url:      str = ""
    source:   str = ""          # "web" | "github" | "arxiv" | "local"

    # Content
    text:     str = ""
    title:    str = ""
    language: str = "en"

    # Classification
    content_type:   str = "unknown"   # see source_weights.yaml content_type_weights
    code_language:  str = ""          # populated for source_code docs
    domain:         str = ""          # registered domain, e.g. "github.com"

    # Quality / weighting signals
    domain_weight:      float = 1.0
    content_type_weight: float = 1.0
    quality_score:      float = 1.0
    final_weight:       float = 1.0

    # Metadata
    stars:        int = 0             # github stars
    citations:    int = 0             # paper citations
    word_count:   int = 0
    char_count:   int = 0
    crawl_depth:  int = 0

    # Pipeline state flags
    flagged:   bool = False
    clean_action: str = ""           # "kept" | "dropped" | "flagged" | "redacted"
    clean_score:  float = 0.0

    # Embedding (populated during dedup stage)
    embedding: Optional[list[float]] = field(default=None, repr=False)
    dedup_cluster_id: str = ""

    # Arbitrary extra metadata
    meta: dict = field(default_factory=dict)

    def to_jsonl(self) -> dict:
        """Serialise to a plain dict for JSONL output. Drops embedding."""
        d = self.__dict__.copy()
        d.pop("embedding", None)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Document":
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)
