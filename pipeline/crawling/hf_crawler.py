"""
huggingface_crawler.py — Pulls text documents from Hugging Face Hub datasets.

Uses the `datasets` library in streaming mode so nothing is downloaded to
disk in full before being consumed — safe for large datasets on limited
hardware.

Config (config/pipeline_config.yaml -> crawl.huggingface):

  huggingface:
    datasets:
      - repo: "wikimedia/wikipedia"
        config: "20231101.en"
        split: "train"
        text_field: "text"
        max_docs: 20000
      - repo: "bigcode/the-stack-smol"
        config: null
        split: "train"
        text_field: "content"
        max_docs: 20000
    token_env: "HF_TOKEN"     # optional, needed for gated/private datasets

Each entry in `datasets` is independent — add or remove entries to control
exactly what data gets pulled in. `max_docs` bounds each dataset so a single
huge source can't dominate the corpus; leave it null to take everything.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Iterator

from pipeline.crawler.base import BaseCrawler
from pipeline.crawler.source_scorer import classify_text, detect_code_language
from pipeline.types import Document

log = logging.getLogger("crawler.huggingface")


class HuggingFaceCrawler(BaseCrawler):

    def __init__(self, cfg: dict, weight_lookup, signal_tracker):
        super().__init__(cfg, weight_lookup, signal_tracker)
        self._hcfg = cfg.get("huggingface", {})
        self._token = os.environ.get(self._hcfg.get("token_env", "HF_TOKEN"), "") or None

    def crawl(self) -> Iterator[Document]:
        try:
            from datasets import load_dataset
        except ImportError:
            log.error("`datasets` not installed — run: pip install datasets huggingface_hub")
            return

        entries = self._hcfg.get("datasets", [])
        if not entries:
            log.warning("No datasets configured under crawl.huggingface.datasets — skipping")
            return

        for entry in entries:
            repo        = entry.get("repo")
            config_name = entry.get("config")
            split       = entry.get("split", "train")
            text_field  = entry.get("text_field", "text")
            max_docs    = entry.get("max_docs")

            if not repo:
                log.warning(f"Skipping huggingface entry with no `repo`: {entry}")
                continue

            log.info(f"HuggingFace: streaming {repo} ({config_name or 'default'}/{split})")
            try:
                ds = load_dataset(
                    repo,
                    config_name,
                    split=split,
                    streaming=True,
                    token=self._token,
                )
            except Exception as e:
                log.warning(f"HuggingFace: failed to open {repo}: {e}")
                self.stats["errors"] += 1
                continue

            n = 0
            for row in ds:
                if max_docs and n >= max_docs:
                    break
                text = row.get(text_field, "")
                if not isinstance(text, str) or len(text.split()) < 30:
                    self.stats["skipped"] += 1
                    continue

                doc_id = hashlib.md5(f"{repo}:{split}:{n}".encode()).hexdigest()
                domain = "huggingface.co"
                ctype = classify_text(text)
                clang = detect_code_language(repo)

                doc = Document(
                    doc_id       = doc_id,
                    url          = f"hf://{repo}/{split}#{n}",
                    source       = "huggingface",
                    text         = text,
                    title        = row.get("title", "") if isinstance(row.get("title", ""), str) else "",
                    domain       = domain,
                    content_type = ctype,
                    code_language = clang,
                    word_count   = len(text.split()),
                    char_count   = len(text),
                    meta         = {"hf_repo": repo, "hf_config": config_name, "hf_split": split},
                )
                doc = self._apply_weights(doc)
                self.stats["fetched"] += 1
                n += 1
                yield doc

            log.info(f"HuggingFace: {repo} → {n} docs")

        self.print_stats()
