"""
web_crawler.py — General purpose web crawler.

Features:
- Reads seed URLs from config/seed_urls.txt + inline per-dataset seeds
- Sitemap discovery (sitemap.xml auto-probe; robots.txt Sitemap: directives)
- Follows links up to max_depth via BFS
- Respects robots.txt
- Per-domain politeness delay with adaptive jitter (breaks deterministic fingerprinting)
- Exponential backoff with jitter; honours Retry-After on 429
- URL allow/blocklist filtering
- Rolling signal gating (abandons low-signal domains after N pages)
- Trafilatura-first extraction (boilerplate-aware, ACL-2021 benchmark winner);
  falls back to BeautifulSoup when trafilatura is not installed
- Optional English-only gating via langdetect
- SHA-256 content deduplication
"""

from __future__ import annotations

import hashlib
import logging
import random
import re
import time
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from typing import Iterator
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from pipeline.crawler.base import BaseCrawler
from pipeline.crawler.source_scorer import (
    classify_url, classify_text, detect_code_language,
    score_document,
)
from pipeline.types import Document
from pipeline.crawler.security import public_http_url

log = logging.getLogger("crawler.web")

try:
    import trafilatura
    _TRAFILATURA_AVAILABLE = True
except ImportError:
    _TRAFILATURA_AVAILABLE = False

try:
    from langdetect import detect as _langdetect
    _LANGDETECT_AVAILABLE = True
except ImportError:
    _LANGDETECT_AVAILABLE = False

_SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def _registered_domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _jitter(base: float, factor: float = 0.25) -> float:
    """Return base ± up to factor*base random offset.

    Breaking deterministic backoff patterns prevents bot-detection fingerprinting.
    """
    return max(0.0, base * (1.0 + random.uniform(-factor, factor)))


class RobotsCache:
    def __init__(self, ua: str, timeout: int):
        self._ua      = ua
        self._timeout = timeout
        self._cache:    dict[str, RobotFileParser] = {}
        self._sitemaps: dict[str, list[str]]       = {}

    def _load(self, base: str) -> None:
        rp = RobotFileParser()
        rp.set_url(f"{base}/robots.txt")
        sm_hints: list[str] = []
        try:
            rp.read()
            # Harvest Sitemap: lines from robots.txt
            if hasattr(rp, "_sitemaps"):
                sm_hints = list(rp._sitemaps)
        except Exception:
            pass
        self._cache[base]    = rp
        self._sitemaps[base] = sm_hints

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        base   = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self._cache:
            self._load(base)
        return self._cache[base].can_fetch(self._ua, url)

    def sitemap_hints(self, base: str) -> list[str]:
        if base not in self._cache:
            self._load(base)
        return self._sitemaps.get(base, [])


class WebCrawler(BaseCrawler):

    def __init__(self, cfg: dict, weight_lookup, signal_tracker):
        super().__init__(cfg, weight_lookup, signal_tracker)
        self._wcfg         = {**cfg, **cfg.get("web", {})}
        self._gcfg         = cfg
        self._session      = self._build_session()
        self._robots       = RobotsCache(cfg["user_agent"], cfg["request_timeout"])
        self._seen_urls:   set[str]  = set()
        self._seen_hashes: set[str]  = set()
        self._domain_last_fetch: defaultdict[str, float] = defaultdict(float)
        self._allow_pats = [re.compile(p) for p in self._wcfg.get("url_allowlist_patterns", [])]
        self._block_pats = [re.compile(p) for p in self._wcfg.get("url_blocklist_patterns", [])]
        self._en_only    = self._wcfg.get("english_only", True)
        self.stats["sitemaps_discovered"] = 0
        self.stats["trafilatura_used"]    = 0
        self.stats["bs4_fallback"]        = 0
        self.stats["lang_rejected"]       = 0

    def _build_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "User-Agent": self._gcfg["user_agent"],
            "Accept-Language": "en-US,en;q=0.9",
        })
        return s

    def _url_allowed(self, url: str) -> bool:
        if not public_http_url(url):
            return False
        for p in self._block_pats:
            if p.search(url):
                return False
        if not self._allow_pats:
            return True
        return any(p.search(url) for p in self._allow_pats)

    def _polite_get(self, url: str) -> requests.Response | None:
        domain  = _registered_domain(url)
        elapsed = time.time() - self._domain_last_fetch[domain]
        delay   = self._gcfg.get("politeness_delay", 1.0)
        if elapsed < delay:
            time.sleep(_jitter(delay - elapsed))

        attempts = self._gcfg.get("retry_attempts", 3)
        backoff  = self._gcfg.get("retry_backoff", 2.0)
        timeout  = self._gcfg.get("request_timeout", 15)

        for attempt in range(attempts):
            try:
                resp = self._session.get(url, timeout=timeout, allow_redirects=False)

                if resp.status_code == 429:
                    wait = float(resp.headers.get("Retry-After", backoff ** (attempt + 1)))
                    log.warning(f"429 rate-limit on {url}, sleeping {wait:.1f}s")
                    time.sleep(_jitter(wait))
                    continue

                if resp.is_redirect or resp.is_permanent_redirect:
                    target = urljoin(url, resp.headers.get("Location", ""))
                    if not public_http_url(target) or not self._url_allowed(target):
                        log.warning(f"Blocked unsafe redirect: {url} -> {target}")
                        return None
                    resp = self._session.get(target, timeout=timeout, allow_redirects=False)

                self._domain_last_fetch[domain] = time.time()
                return resp

            except Exception as e:
                if attempt == attempts - 1:
                    log.warning(f"FETCH FAILED {url}: {e}")
                    self.stats["errors"] += 1
                    return None
                time.sleep(_jitter(backoff ** attempt))
        return None

    # ── Sitemap discovery ──────────────────────────────────────────────────

    def _parse_sitemap(self, xml_text: str) -> list[str]:
        urls: list[str] = []
        try:
            root = ET.fromstring(xml_text)
            for sm in root.findall(f"{{{_SITEMAP_NS}}}sitemap"):
                loc = sm.find(f"{{{_SITEMAP_NS}}}loc")
                if loc is not None and loc.text:
                    child = self._fetch_sitemap_url(loc.text.strip())
                    urls.extend(child)
            for url_el in root.findall(f"{{{_SITEMAP_NS}}}url"):
                loc = url_el.find(f"{{{_SITEMAP_NS}}}loc")
                if loc is not None and loc.text:
                    urls.append(loc.text.strip())
        except ET.ParseError:
            pass
        return urls

    def _fetch_sitemap_url(self, sitemap_url: str) -> list[str]:
        try:
            resp = self._session.get(sitemap_url, timeout=10)
            if resp.status_code == 200:
                return self._parse_sitemap(resp.text)
        except Exception:
            pass
        return []

    def _discover_sitemaps(self, seeds: list[str]) -> list[str]:
        """Probe sitemap.xml for each unique seed domain."""
        discovered: list[str] = []
        seen_bases: set[str] = set()
        for seed in seeds:
            p    = urlparse(seed)
            base = f"{p.scheme}://{p.netloc}"
            if base in seen_bases:
                continue
            seen_bases.add(base)
            # robots.txt Sitemap: hints first
            hints = self._robots.sitemap_hints(base)
            for hint in hints:
                discovered.extend(self._fetch_sitemap_url(hint))
            # Direct sitemap.xml probe
            sm_urls = self._fetch_sitemap_url(f"{base}/sitemap.xml")
            discovered.extend(sm_urls)
        return discovered

    # ── Text extraction ────────────────────────────────────────────────────

    def _extract_text_trafilatura(self, html: str, url: str) -> tuple[str, str, list[str]]:
        text   = trafilatura.extract(html, url=url, include_links=False,
                                     include_comments=False, output_format="txt",
                                     no_fallback=False) or ""
        meta   = trafilatura.extract_metadata(html, default_url=url)
        title  = (meta.title or "") if meta else ""
        # Still need outlinks for BFS — trafilatura doesn't expose them in txt mode
        soup  = BeautifulSoup(html, "lxml")
        base  = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        links = [urljoin(base, a["href"]) for a in soup.find_all("a", href=True)
                 if urljoin(base, a["href"]).startswith("http")]
        return title, text, links

    def _extract_text_bs4(self, html: str, url: str) -> tuple[str, str, list[str]]:
        soup  = BeautifulSoup(html, "lxml")
        title = soup.title.string.strip() if soup.title else ""
        for tag in soup(["script", "style", "nav", "footer", "aside",
                          "header", "form", "noscript", "iframe",
                          "button", "select", "[class*='menu']",
                          "[class*='sidebar']", "[class*='ad']"]):
            tag.decompose()
        text = re.sub(r"\n{3,}", "\n\n", soup.get_text(separator="\n")).strip()
        base  = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        links = [urljoin(base, a["href"]) for a in soup.find_all("a", href=True)
                 if urljoin(base, a["href"]).startswith("http")]
        return title, text, links

    def _extract_text(self, html: str, url: str) -> tuple[str, str, list[str]]:
        if _TRAFILATURA_AVAILABLE:
            title, text, links = self._extract_text_trafilatura(html, url)
            if text and len(text.split()) >= 30:
                self.stats["trafilatura_used"] += 1
                return title, text, links
        self.stats["bs4_fallback"] += 1
        return self._extract_text_bs4(html, url)

    def _is_english(self, text: str) -> bool:
        if not _LANGDETECT_AVAILABLE or not self._en_only:
            return True
        try:
            return _langdetect(text[:2000]) == "en"
        except Exception:
            return True

    def _doc_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()

    # ── Main crawl loop ────────────────────────────────────────────────────

    def crawl(self) -> Iterator[Document]:
        seed_file = self._wcfg.get("seed_urls_file", "config/seed_urls.txt")
        seeds: list[str] = list(self._wcfg.get("seed_urls", []))
        try:
            with open(seed_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        seeds.append(line)
        except FileNotFoundError:
            if not seeds:
                log.error(f"Seed URL file not found: {seed_file}")
                return

        max_depth   = self._wcfg.get("max_depth", 3)
        max_pages   = self._gcfg.get("max_pages_per_domain", 500)
        max_bytes   = self._gcfg.get("max_content_bytes", 5_000_000)
        use_sitemap = self._wcfg.get("use_sitemap_discovery", True)
        domain_counts: defaultdict[str, int] = defaultdict(int)

        queue: deque[tuple[str, int]] = deque((u, 0) for u in seeds)

        if use_sitemap:
            sm_urls = self._discover_sitemaps(seeds)
            if sm_urls:
                log.info(f"Sitemap discovery: {len(sm_urls)} URLs found")
                self.stats["sitemaps_discovered"] += len(sm_urls)
                for u in sm_urls:
                    if u not in self._seen_urls:
                        queue.append((u, 1))

        while queue:
            url, depth = queue.popleft()

            if url in self._seen_urls:
                continue
            self._seen_urls.add(url)

            if not self._url_allowed(url):
                self.stats["skipped"] += 1
                continue

            domain = _registered_domain(url)

            if self.signal_tracker.should_abandon(domain):
                self.stats["abandoned_domains"] += 1
                continue

            if domain_counts[domain] >= max_pages:
                self.stats["skipped"] += 1
                continue

            if self._gcfg.get("respect_robots_txt", True) and not self._robots.allowed(url):
                self.stats["skipped"] += 1
                continue

            resp = self._polite_get(url)
            if resp is None or resp.status_code != 200:
                continue

            ct = resp.headers.get("content-type", "")
            if "text/html" not in ct and "text/plain" not in ct:
                self.stats["skipped"] += 1
                continue

            if len(resp.content) > max_bytes:
                self.stats["skipped"] += 1
                continue

            try:
                html = resp.text
            except Exception:
                self.stats["errors"] += 1
                continue

            title, text, outlinks = self._extract_text(html, url)
            if not text or len(text.split()) < 30:
                self.stats["skipped"] += 1
                continue

            if not self._is_english(text):
                self.stats["lang_rejected"] += 1
                self.stats["skipped"] += 1
                continue

            h = self._doc_hash(text)
            if h in self._seen_hashes:
                self.stats["skipped"] += 1
                continue
            self._seen_hashes.add(h)

            sig = score_document(url, text)
            self.signal_tracker.record(domain, sig)

            url_type  = classify_url(url)
            text_type = classify_text(text)
            ctype = url_type if url_type != "unknown" else text_type
            clang = detect_code_language(url)

            doc = Document(
                doc_id        = hashlib.md5(url.encode()).hexdigest(),
                url           = url,
                source        = "web",
                text          = text,
                title         = title,
                domain        = domain,
                content_type  = ctype,
                code_language = clang,
                word_count    = len(text.split()),
                char_count    = len(text),
                crawl_depth   = depth,
            )
            doc = self._apply_weights(doc)
            domain_counts[domain] += 1
            self.stats["fetched"] += 1

            log.info(f"FETCH [{depth}] {url} | type={ctype} w={doc.final_weight:.2f}")
            yield doc

            if depth < max_depth:
                for link in outlinks:
                    if link not in self._seen_urls:
                        queue.append((link, depth + 1))

        self.print_stats()
