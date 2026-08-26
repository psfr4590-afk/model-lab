"""
arxiv_crawler.py — Fetches paper metadata, abstracts, and optionally full text from ArXiv.

Optionally enriches each paper with citation counts from Semantic Scholar (free API,
no key required, 100 req/min). Citations populate Document.citations for downstream
weighting.

PDF extraction requires pdfminer.six. Abstracts-only is the default (fast, no overhead).
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Iterator

import requests

from pipeline.crawler.base import BaseCrawler
from pipeline.types import Document

log = logging.getLogger("crawler.arxiv")

_ATOM_NS  = "http://www.w3.org/2005/Atom"
_ARXIV_NS = "http://arxiv.org/schemas/atom"
_API_URL  = "https://export.arxiv.org/api/query"
_PDF_BASE = "https://arxiv.org/pdf"

# Semantic Scholar public API — no key required, 100 req/min
_S2_API = "https://api.semanticscholar.org/graph/v1/paper"

_DELAY_BETWEEN_REQUESTS = 3.0


class ArxivCrawler(BaseCrawler):

    def __init__(self, cfg: dict, weight_lookup, signal_tracker):
        super().__init__(cfg, weight_lookup, signal_tracker)
        self._acfg    = cfg.get("arxiv", {})
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": cfg.get("user_agent", "PretrainBot/1.0")})
        self._seen: set[str] = set()
        self._cite_cache: dict[str, int] = {}
        self.stats["citations_enriched"] = 0
        self.stats["pdf_extracted"]      = 0

    def _query(self, category: str, start: int, max_results: int) -> str | None:
        params = {
            "search_query": f"cat:{category}",
            "start":        start,
            "max_results":  min(max_results, 100),
            "sortBy":       "lastUpdatedDate",
            "sortOrder":    "descending",
        }
        try:
            r = self._session.get(_API_URL, params=params, timeout=30)
            if r.status_code == 200:
                return r.text
            log.warning(f"ArXiv API {r.status_code} for {category} start={start}")
        except Exception as e:
            log.warning(f"ArXiv request error: {e}")
        return None

    def _parse_feed(self, xml_text: str) -> list[dict]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            log.warning(f"ArXiv XML parse error: {e}")
            return []

        papers = []
        for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
            def tag(name, ns=_ATOM_NS, entry=entry):
                el = entry.find(f"{{{ns}}}{name}")
                return el.text.strip() if el is not None and el.text else ""

            arxiv_id  = tag("id").split("/abs/")[-1].split("v")[0].strip()
            title     = re.sub(r"\s+", " ", tag("title"))
            abstract  = re.sub(r"\s+", " ", tag("summary"))
            published = tag("published")
            updated   = tag("updated")
            doi       = tag("doi", _ARXIV_NS)
            comment   = tag("comment", _ARXIV_NS)

            authors = [
                a.find(f"{{{_ATOM_NS}}}name").text.strip()
                for a in entry.findall(f"{{{_ATOM_NS}}}author")
                if a.find(f"{{{_ATOM_NS}}}name") is not None
            ]
            categories = [c.get("term", "") for c in entry.findall(f"{{{_ATOM_NS}}}category")]

            papers.append({
                "arxiv_id":   arxiv_id,
                "title":      title,
                "abstract":   abstract,
                "authors":    authors,
                "categories": categories,
                "published":  published,
                "updated":    updated,
                "doi":        doi,
                "comment":    comment,
            })
        return papers

    def _fetch_citations(self, arxiv_id: str) -> int:
        """Query Semantic Scholar for citation count (no API key needed)."""
        if arxiv_id in self._cite_cache:
            return self._cite_cache[arxiv_id]
        try:
            url = f"{_S2_API}/arXiv:{arxiv_id}"
            r   = self._session.get(url, params={"fields": "citationCount"}, timeout=10)
            if r.status_code == 200:
                count = r.json().get("citationCount", 0) or 0
                self._cite_cache[arxiv_id] = count
                return count
        except Exception:
            pass
        return 0

    def _fetch_pdf_text(self, arxiv_id: str) -> str:
        try:
            from pdfminer.high_level import extract_text_to_fp
            from pdfminer.layout import LAParams
            import io

            url = f"{_PDF_BASE}/{arxiv_id}"
            r   = self._session.get(url, timeout=60, stream=True)
            if r.status_code != 200:
                return ""

            out = io.StringIO()
            extract_text_to_fp(
                io.BytesIO(r.content), out,
                laparams=LAParams(), output_type="text", codec="utf-8"
            )
            text = out.getvalue()
            text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
            text = re.sub(r"\n{3,}", "\n\n", text)
            return text.strip()
        except ImportError:
            log.warning("pdfminer.six not installed; abstract-only mode")
            return ""
        except Exception as e:
            log.warning(f"PDF extraction failed for {arxiv_id}: {e}")
            return ""

    def _make_doc(self, paper: dict, text: str, source_mode: str, citations: int) -> Document:
        arxiv_id  = paper["arxiv_id"]
        url       = f"https://arxiv.org/abs/{arxiv_id}"

        structured = (
            f"Title: {paper['title']}\n"
            f"Authors: {', '.join(paper['authors'][:6])}\n"
            f"Categories: {', '.join(paper['categories'])}\n"
            f"Published: {paper['published'][:10]}\n"
        )
        if paper.get("doi"):
            structured += f"DOI: {paper['doi']}\n"
        if citations:
            structured += f"Citations: {citations}\n"
        structured += f"\nAbstract:\n{paper['abstract']}\n"
        if text and source_mode == "full":
            structured += f"\nFull Text:\n{text}\n"

        doc = Document(
            doc_id       = hashlib.md5(url.encode()).hexdigest(),
            url          = url,
            source       = "arxiv",
            text         = structured,
            title        = paper["title"],
            domain       = "arxiv.org",
            content_type = "research_paper",
            citations    = citations,
            word_count   = len(structured.split()),
            char_count   = len(structured),
            meta         = {
                "arxiv_id":    arxiv_id,
                "authors":     paper["authors"],
                "categories":  paper["categories"],
                "published":   paper["published"],
                "doi":         paper.get("doi", ""),
                "source_mode": source_mode,
                "citations":   citations,
            },
        )
        doc = self._apply_weights(doc)

        # Citation boost: highly-cited papers get a small weight bump (log-scaled)
        if citations > 0:
            import math
            cite_bonus = min(math.log10(citations + 1) / 6.0, 0.3)
            doc.final_weight = min(doc.final_weight + cite_bonus, 5.0)

        return doc

    def crawl(self) -> Iterator[Document]:
        categories     = self._acfg.get("categories", ["cs.AI"])
        max_per_cat    = self._acfg.get("max_results_per_category", 1000)
        full_text      = self._acfg.get("fetch_full_text", False)
        enrich_cites   = self._acfg.get("enrich_citations", True)
        source_mode    = "full" if full_text else "abstract"

        for cat in categories:
            log.info(f"ArXiv: fetching category {cat} (max={max_per_cat})")
            fetched_this_cat = 0
            start = 0
            batch = 100

            while fetched_this_cat < max_per_cat:
                remaining = max_per_cat - fetched_this_cat
                xml_text  = self._query(cat, start, min(batch, remaining))
                if not xml_text:
                    break

                papers = self._parse_feed(xml_text)
                if not papers:
                    break

                for paper in papers:
                    arxiv_id = paper["arxiv_id"]
                    if not arxiv_id or arxiv_id in self._seen:
                        self.stats["skipped"] += 1
                        continue

                    if not paper.get("abstract") or len(paper["abstract"].split()) < 20:
                        self.stats["skipped"] += 1
                        continue

                    self._seen.add(arxiv_id)

                    citations = 0
                    if enrich_cites:
                        citations = self._fetch_citations(arxiv_id)
                        if citations:
                            self.stats["citations_enriched"] += 1
                        time.sleep(0.6)   # S2 rate limit: ~100 req/min

                    full = ""
                    if full_text:
                        full = self._fetch_pdf_text(arxiv_id)
                        if full:
                            self.stats["pdf_extracted"] += 1
                        time.sleep(1.0)

                    doc = self._make_doc(paper, full, source_mode, citations)
                    log.debug(f"ArXiv {arxiv_id}: {paper['title'][:60]} "
                              f"citations={citations} w={doc.final_weight:.2f}")
                    yield doc
                    self.stats["fetched"] += 1
                    fetched_this_cat += 1

                start += len(papers)
                if len(papers) < batch:
                    break

                time.sleep(_DELAY_BETWEEN_REQUESTS)

        self.print_stats()
