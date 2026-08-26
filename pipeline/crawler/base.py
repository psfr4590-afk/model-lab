"""
base.py — Abstract base class for all crawlers.
"""

from __future__ import annotations

import abc
import logging
from typing import Iterator

from pipeline.types import Document

log = logging.getLogger("crawler.base")


class BaseCrawler(abc.ABC):
    """Every crawler yields Document objects."""

    def __init__(self, cfg: dict, weight_lookup, signal_tracker):
        self.cfg            = cfg
        self.weight_lookup  = weight_lookup
        self.signal_tracker = signal_tracker
        self.stats = {"fetched": 0, "skipped": 0, "errors": 0, "abandoned_domains": 0}

    @abc.abstractmethod
    def crawl(self) -> Iterator[Document]:
        ...

    def _apply_weights(self, doc: Document) -> Document:
        dw, category = self.weight_lookup.domain_weight(doc.domain)
        ctw = self.weight_lookup.content_type_weight(doc.content_type)
        qs  = self.weight_lookup.quality_score(doc.text)

        doc.domain_weight       = dw
        doc.content_type_weight = ctw
        doc.quality_score       = qs

        # Code language multiplier
        if doc.content_type == "source_code" and doc.code_language:
            lang_w = self.weight_lookup.code_language_weight(doc.code_language)
            ctw   *= lang_w

        doc.final_weight = dw * ctw * qs
        if not doc.meta.get("category"):
            doc.meta["category"] = category
        return doc

    def print_stats(self):
        s = self.stats
        log.info(
            f"{self.__class__.__name__} | fetched={s['fetched']} "
            f"skipped={s['skipped']} errors={s['errors']} "
            f"abandoned_domains={s['abandoned_domains']}"
        )
