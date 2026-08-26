"""
google_crawler.py

Optional Google Search discovery + direct public URL crawling.

Two discovery modes are supported:

1. google_search
   Uses Google Programmable Search / Custom Search JSON API.
   Requires:
       GOOGLE_API_KEY
       GOOGLE_CX

2. direct_public_url
   Fetches explicitly configured public URLs directly.
   Requires NO Google credentials.

Direct URLs are still subject to the crawler's normal:
    - public HTTP/HTTPS validation
    - robots.txt policy
    - politeness delay
    - request timeout
    - content-size limits
    - duplicate detection
    - source scoring

Recommended architecture:
    - Use WebCrawler for normal known/public URL seeds.
    - Use GoogleCrawler direct seed_urls only when you specifically
      want those documents attributed to GoogleCrawler.
    - Use Google Search only when search-based discovery is desired.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from collections import defaultdict
from typing import Iterator
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from pipeline.crawler.base import BaseCrawler
from pipeline.crawler.security import public_http_url
from pipeline.crawler.source_scorer import (
    classify_text,
    classify_url,
    detect_code_language,
    score_document,
)
from pipeline.types import Document

log = logging.getLogger("crawler.google")

_CSE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"


def _registered_domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


class RobotsCache:
    """
    Cached robots.txt parser.

    This intentionally preserves the existing crawler behavior:
    if robots.txt cannot be retrieved, RobotFileParser may permit
    the URL. We are not changing that policy as part of the Google
    crawler architecture change.
    """

    def __init__(self, ua: str):
        self._ua = ua
        self._cache: dict[str, RobotFileParser] = {}

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"

        if base not in self._cache:
            rp = RobotFileParser()
            rp.set_url(f"{base}/robots.txt")
            try:
                rp.read()
            except Exception:
                pass
            self._cache[base] = rp

        return self._cache[base].can_fetch(self._ua, url)


class GoogleCrawler(BaseCrawler):

    def __init__(self, cfg: dict, weight_lookup, signal_tracker):
        super().__init__(cfg, weight_lookup, signal_tracker)

        self._gcfg = cfg.get("google", {})
        self._crawlcfg = cfg

        self._api_key = os.environ.get(
            self._gcfg.get("api_key_env", "GOOGLE_API_KEY"),
            "",
        )

        self._cx = os.environ.get(
            self._gcfg.get("cx_env", "GOOGLE_CX"),
            "",
        )

        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": cfg.get(
                    "user_agent",
                    "PretrainPipeline/1.1 (local research dataset builder)",
                ),
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

        self._robots = RobotsCache(
            cfg.get(
                "user_agent",
                "PretrainPipeline/1.1 (local research dataset builder)",
            )
        )

        self._seen_urls: set[str] = set()
        self._seen_hashes: set[str] = set()

        self._domain_last_fetch: defaultdict[str, float] = defaultdict(float)
        self._domain_counts: defaultdict[str, int] = defaultdict(int)

    def _url_allowed(self, url: str) -> bool:
        """
        Validate that the target is a public HTTP/HTTPS URL.

        Direct GoogleCrawler seeds intentionally use the same security
        primitive as WebCrawler.
        """
        return public_http_url(url)

    def _polite_get(self, url: str) -> requests.Response | None:
        """
        Fetch a URL while respecting the global crawler politeness policy.

        Redirects are validated before being followed so a public seed
        cannot silently redirect into a private/local destination.
        """
        domain = _registered_domain(url)

        elapsed = time.time() - self._domain_last_fetch[domain]
        delay = self._crawlcfg.get("politeness_delay", 1.0)

        if elapsed < delay:
            time.sleep(delay - elapsed)

        retry_attempts = self._crawlcfg.get("retry_attempts", 3)
        retry_backoff = self._crawlcfg.get("retry_backoff", 2.0)
        timeout = self._crawlcfg.get("request_timeout", 15)
        max_redirects = self._crawlcfg.get("max_redirects", 3)

        current_url = url

        for attempt in range(retry_attempts):
            try:
                redirects = 0

                while redirects <= max_redirects:
                    if not self._url_allowed(current_url):
                        log.warning(
                            "Blocked unsafe GoogleCrawler URL: %s",
                            current_url,
                        )
                        return None

                    resp = self._session.get(
                        current_url,
                        timeout=timeout,
                        allow_redirects=False,
                    )

                    self._domain_last_fetch[domain] = time.time()

                    if not (
                        resp.is_redirect
                        or resp.is_permanent_redirect
                    ):
                        return resp

                    target = urljoin(
                        current_url,
                        resp.headers.get("Location", ""),
                    )

                    if not self._url_allowed(target):
                        log.warning(
                            "Blocked unsafe redirect: %s -> %s",
                            current_url,
                            target,
                        )
                        return None

                    current_url = target
                    redirects += 1

                log.warning(
                    "Maximum redirects exceeded for %s",
                    url,
                )
                self.stats["skipped"] += 1
                return None

            except Exception as exc:
                if attempt == retry_attempts - 1:
                    log.warning(
                        "FETCH FAILED %s: %s",
                        url,
                        exc,
                    )
                    self.stats["errors"] += 1
                    return None

                time.sleep(retry_backoff ** attempt)

        return None

    def _search(self, query: str, num: int) -> list[str]:
        """
        Optional Google Search discovery.

        Missing credentials are NOT fatal. Search discovery is simply
        skipped, while direct seed_urls continue to work.
        """
        if not self._api_key or not self._cx:
            log.info(
                "Google Search discovery disabled for '%s': "
                "GOOGLE_API_KEY / GOOGLE_CX not configured. "
                "Direct public seed_urls remain enabled.",
                query,
            )
            return []

        urls: list[str] = []
        start = 1

        while len(urls) < num:
            batch = min(10, num - len(urls))

            try:
                resp = self._session.get(
                    _CSE_ENDPOINT,
                    params={
                        "key": self._api_key,
                        "cx": self._cx,
                        "q": query,
                        "num": batch,
                        "start": start,
                    },
                    timeout=15,
                )

                if resp.status_code != 200:
                    log.warning(
                        "Google CSE %s for '%s': %s",
                        resp.status_code,
                        query,
                        resp.text[:200],
                    )
                    break

                items = resp.json().get("items", [])

            except Exception as exc:
                log.warning(
                    "Google CSE request failed for '%s': %s",
                    query,
                    exc,
                )
                self.stats["errors"] += 1
                break

            if not items:
                break

            for item in items:
                link = item.get("link")

                if link:
                    urls.append(link)

            start += batch

        return urls[:num]

    def _extract_text(self, html: str) -> tuple[str, str]:
        soup = BeautifulSoup(html, "lxml")

        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()

        for tag in soup(
            [
                "script",
                "style",
                "nav",
                "footer",
                "aside",
                "header",
                "form",
                "noscript",
                "iframe",
                "button",
                "select",
            ]
        ):
            tag.decompose()

        text = soup.get_text(separator="\n")
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        return title, text

    def _fetch_document(
        self,
        url: str,
        discovery: str,
        query: str | None = None,
    ) -> Document | None:
        """
        Fetch and convert one URL into a Document.
        """
        if not self._url_allowed(url):
            self.stats["skipped"] += 1
            return None

        if (
            self._crawlcfg.get("respect_robots_txt", True)
            and not self._robots.allowed(url)
        ):
            log.info("ROBOTS BLOCK [%s] %s", discovery, url)
            self.stats["skipped"] += 1
            return None

        domain = _registered_domain(url)

        max_per_domain = self._crawlcfg.get(
            "max_pages_per_domain",
            500,
        )

        if self._domain_counts[domain] >= max_per_domain:
            self.stats["skipped"] += 1
            return None

        if self.signal_tracker.should_abandon(domain):
            self.stats["abandoned_domains"] += 1
            return None

        resp = self._polite_get(url)

        if resp is None:
            return None

        if resp.status_code != 200:
            self.stats["skipped"] += 1
            return None

        content_type = resp.headers.get("content-type", "").lower()

        if "text/html" not in content_type and "text/plain" not in content_type:
            self.stats["skipped"] += 1
            return None

        max_bytes = self._crawlcfg.get(
            "max_content_bytes",
            5_000_000,
        )

        if len(resp.content) > max_bytes:
            log.info(
                "SKIP oversized page %s (%d bytes)",
                url,
                len(resp.content),
            )
            self.stats["skipped"] += 1
            return None

        try:
            title, text = self._extract_text(resp.text)
        except Exception as exc:
            log.warning(
                "TEXT EXTRACTION FAILED %s: %s",
                url,
                exc,
            )
            self.stats["errors"] += 1
            return None

        if not text or len(text.split()) < 30:
            self.stats["skipped"] += 1
            return None

        document_hash = hashlib.sha256(
            text.encode(
                "utf-8",
                errors="replace",
            )
        ).hexdigest()

        if document_hash in self._seen_hashes:
            self.stats["skipped"] += 1
            return None

        self._seen_hashes.add(document_hash)

        sig = score_document(url, text)
        self.signal_tracker.record(domain, sig)

        url_type = classify_url(url)
        text_type = classify_text(text)

        content_type_class = (
            url_type
            if url_type != "unknown"
            else text_type
        )

        meta = {
            "discovery": discovery,
        }

        if query is not None:
            meta["query"] = query

        doc = Document(
            doc_id=hashlib.md5(
                url.encode()
            ).hexdigest(),
            url=url,
            source="google",
            text=text,
            title=title,
            domain=domain,
            content_type=content_type_class,
            code_language=detect_code_language(url),
            word_count=len(text.split()),
            char_count=len(text),
            meta=meta,
        )

        doc = self._apply_weights(doc)

        self._domain_counts[domain] += 1
        self.stats["fetched"] += 1

        log.info(
            "FETCH [%s] %s | type=%s w=%.2f",
            discovery,
            url,
            content_type_class,
            doc.final_weight,
        )

        return doc

    def crawl(self) -> Iterator[Document]:
        """
        Crawl direct public URLs first, then optionally perform Google
        Search discovery.

        Direct seed URLs do not require Google credentials.
        """
        seed_urls = self._gcfg.get("seed_urls", [])
        queries = self._gcfg.get("queries", [])

        results_per_query = self._gcfg.get(
            "results_per_query",
            10,
        )

        max_pages_per_query = self._gcfg.get(
            "max_pages_per_query",
            results_per_query,
        )

        max_direct_urls = self._gcfg.get(
            "max_seed_urls",
            500,
        )

        # ------------------------------------------------------------
        # 1. Direct public URL discovery
        # ------------------------------------------------------------

        if seed_urls:
            log.info(
                "GoogleCrawler: processing %d direct public seed URL(s)",
                len(seed_urls),
            )

        direct_count = 0

        for url in seed_urls:
            if direct_count >= max_direct_urls:
                break

            if not isinstance(url, str):
                continue

            url = url.strip()

            if not url:
                continue

            if url in self._seen_urls:
                continue

            self._seen_urls.add(url)

            doc = self._fetch_document(
                url=url,
                discovery="direct_public_url",
            )

            if doc is not None:
                direct_count += 1
                yield doc

        # ------------------------------------------------------------
        # 2. Optional Google Search discovery
        # ------------------------------------------------------------

        for query in queries:
            log.info(
                "Google: searching '%s'",
                query,
            )

            urls = self._search(
                query,
                results_per_query,
            )

            fetched_this_query = 0

            for url in urls:
                if fetched_this_query >= max_pages_per_query:
                    break

                if url in self._seen_urls:
                    continue

                self._seen_urls.add(url)

                doc = self._fetch_document(
                    url=url,
                    discovery="google_search",
                    query=query,
                )

                if doc is not None:
                    fetched_this_query += 1
                    yield doc

        self.print_stats()
