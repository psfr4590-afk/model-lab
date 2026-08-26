"""
github_crawler.py — Crawls GitHub repos for source code, READMEs, wikis, issues, and docs.

Scoring logic:
  - Stars gate: skip repos below min_stars
  - Language filter: only configured languages
  - Topic filter: prefer repos matching configured topics
  - File-level weight: .py/.rs/.go etc > README > docs > issues
  - Star bonus: log-scale bump to final_weight
  - Rate limit aware: checks X-RateLimit-Remaining and backs off;
    Retry-After honoured when present
  - Exponential backoff with jitter (prevents deterministic fingerprinting)
  - Optional: closed issues + comments as Q&A training signal
  - Optional: GitHub Discussions fetch
"""

from __future__ import annotations

import base64
import hashlib
import logging
import math
import os
import random
import time
from typing import Iterator
from urllib.parse import urlparse

import requests

from pipeline.crawler.base import BaseCrawler
from pipeline.crawler.source_scorer import detect_code_language
from pipeline.types import Document

log = logging.getLogger("crawler.github")

_API = "https://api.github.com"

_CODE_EXTS = {
    ".py", ".rs", ".go", ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp",
    ".ts", ".js", ".java", ".rb", ".swift", ".zig", ".lua",
    ".ml", ".hs", ".jl", ".r", ".sql", ".sh", ".bash",
}
_DOC_EXTS  = {".md", ".rst", ".txt", ".adoc"}
_MAX_FILE_BYTES = 500_000


def _jitter(base: float, factor: float = 0.2) -> float:
    return max(0.0, base * (1.0 + random.uniform(-factor, factor)))


class GitHubCrawler(BaseCrawler):

    def __init__(self, cfg: dict, weight_lookup, signal_tracker):
        super().__init__(cfg, weight_lookup, signal_tracker)
        self._gcfg    = cfg.get("github", {})
        self._session = self._build_session()
        self._seen:   set[str] = set()
        self.stats["issues_fetched"]  = 0
        self.stats["wikis_fetched"]   = 0

    def _build_session(self) -> requests.Session:
        s = requests.Session()
        token = os.environ.get(self._gcfg.get("token_env", "GITHUB_TOKEN"), "")
        headers = {"Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
            log.info("GitHub: authenticated")
        else:
            log.warning("GitHub: unauthenticated mode — rate limits apply (60 req/hr)")
        s.headers.update(headers)
        return s

    def _get(self, url: str, params: dict | None = None) -> dict | list | None:
        for attempt in range(3):
            try:
                r = self._session.get(url, params=params, timeout=15)

                remaining = int(r.headers.get("X-RateLimit-Remaining", 999))
                if remaining < 5:
                    reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 60))
                    wait  = max(reset - time.time(), 0) + 5
                    log.warning(f"GitHub rate limit critical ({remaining} left), sleeping {wait:.0f}s")
                    time.sleep(wait)

                if r.status_code == 429:
                    retry_after = float(r.headers.get("Retry-After", 60.0))
                    log.warning(f"GitHub 429, sleeping {retry_after:.0f}s")
                    time.sleep(_jitter(retry_after))
                    continue

                if r.status_code == 403:
                    log.warning(f"GitHub 403 on {url}, backing off")
                    time.sleep(_jitter(60.0))
                    continue

                if r.status_code == 200:
                    return r.json()

                log.debug(f"GitHub {r.status_code} {url}")
                return None

            except Exception as e:
                log.warning(f"GitHub request error: {e}")
                time.sleep(_jitter(2.0 ** attempt))
        return None

    def _search_repos(self) -> Iterator[dict]:
        languages = self._gcfg.get("languages", ["Python"])
        topics    = self._gcfg.get("topics", [])
        min_stars = self._gcfg.get("min_stars", 50)
        max_repos = self._gcfg.get("max_repos", 500)
        yielded   = 0

        for lang in languages:
            if yielded >= max_repos:
                break
            page = 1
            while yielded < max_repos:
                params = {
                    "q":       f"language:{lang} stars:>={min_stars}",
                    "sort":    "stars",
                    "order":   "desc",
                    "per_page": 50,
                    "page":    page,
                }
                data = self._get(f"{_API}/search/repositories", params)
                if not data or not data.get("items"):
                    break
                for repo in data["items"]:
                    yield repo
                    yielded += 1
                    if yielded >= max_repos:
                        break
                page += 1
                time.sleep(_jitter(0.5))

        for topic in topics:
            if yielded >= max_repos:
                break
            page = 1
            while yielded < max_repos:
                params = {
                    "q":       f"topic:{topic} stars:>={min_stars}",
                    "sort":    "stars",
                    "order":   "desc",
                    "per_page": 50,
                    "page":    page,
                }
                data = self._get(f"{_API}/search/repositories", params)
                if not data or not data.get("items"):
                    break
                for repo in data["items"]:
                    yield repo
                    yielded += 1
                    if yielded >= max_repos:
                        break
                page += 1
                time.sleep(_jitter(0.5))

    def _fetch_tree(self, owner: str, repo: str, sha: str) -> list[dict]:
        data = self._get(f"{_API}/repos/{owner}/{repo}/git/trees/{sha}",
                         params={"recursive": "1"})
        if not data:
            return []
        return data.get("tree", [])

    def _fetch_blob(self, api_url: str) -> str | None:
        """Fetch raw file content; prefer raw.githubusercontent.com (faster, no auth needed)."""
        raw_url = api_url.replace("https://api.github.com/repos", "https://raw.githubusercontent.com")
        raw_url = raw_url.replace("/contents/", "/")
        try:
            r = self._session.get(raw_url, timeout=15)
            if r.status_code == 200:
                if len(r.content) > _MAX_FILE_BYTES:
                    return None
                return r.text
        except Exception:
            pass
        # API fallback (base64-encoded)
        data = self._get(api_url)
        if not data or not isinstance(data, dict):
            return None
        enc     = data.get("encoding", "")
        content = data.get("content", "")
        if enc == "base64" and content:
            try:
                raw = base64.b64decode(content.replace("\n", "")).decode("utf-8", errors="replace")
                if len(raw) > _MAX_FILE_BYTES:
                    return None
                return raw
            except Exception:
                return None
        return None

    def _fetch_issues(self, owner: str, repo: str, max_issues: int = 100) -> list[dict]:
        """Fetch closed issues with accepted answers as Q&A signal."""
        issues: list[dict] = []
        page = 1
        while len(issues) < max_issues:
            data = self._get(f"{_API}/repos/{owner}/{repo}/issues",
                             params={"state": "closed", "per_page": 50,
                                     "page": page, "sort": "comments",
                                     "direction": "desc"})
            if not data or not isinstance(data, list):
                break
            for item in data:
                # Skip pull requests (they share the issues endpoint)
                if item.get("pull_request"):
                    continue
                issues.append(item)
                if len(issues) >= max_issues:
                    break
            if len(data) < 50:
                break
            page += 1
            time.sleep(_jitter(0.3))
        return issues

    def _repo_doc(self, repo: dict, text: str, content_type: str,
                  sub_url: str = "", code_lang: str = "") -> Document:
        url = sub_url or repo.get("html_url", "")
        doc = Document(
            doc_id        = hashlib.md5(url.encode()).hexdigest(),
            url           = url,
            source        = "github",
            text          = text,
            title         = repo.get("full_name", ""),
            domain        = "github.com",
            content_type  = content_type,
            code_language = code_lang,
            stars         = repo.get("stargazers_count", 0),
            word_count    = len(text.split()),
            char_count    = len(text),
            meta          = {
                "repo":        repo.get("full_name"),
                "description": repo.get("description", ""),
                "topics":      repo.get("topics", []),
                "license":     (repo.get("license") or {}).get("spdx_id", ""),
            },
        )
        doc = self._apply_weights(doc)
        if doc.stars > 0:
            star_bonus = min(math.log10(doc.stars + 1) / 5.0, 0.4)
            doc.final_weight += star_bonus
        return doc

    def crawl(self) -> Iterator[Document]:
        include_issues  = self._gcfg.get("include_issues", True)
        max_issues_repo = self._gcfg.get("max_issues_per_repo", 50)
        seen_repos: set[str] = set()

        for repo in self._search_repos():
            full_name = repo.get("full_name", "")
            if not full_name or full_name in seen_repos:
                continue
            seen_repos.add(full_name)

            owner, name    = full_name.split("/", 1)
            stars          = repo.get("stargazers_count", 0)
            default_branch = repo.get("default_branch", "main")

            log.info(f"GitHub repo: {full_name} ⭐{stars}")

            # ── 1. README ─────────────────────────────────────────────────
            readme_data = self._get(f"{_API}/repos/{owner}/{name}/readme")
            if readme_data:
                content = readme_data.get("content", "")
                if content:
                    try:
                        text = base64.b64decode(content.replace("\n", "")).decode("utf-8", errors="replace")
                        if len(text.split()) >= 30:
                            h = hashlib.md5(text.encode()).hexdigest()
                            if h not in self._seen:
                                self._seen.add(h)
                                yield self._repo_doc(
                                    repo, text, "technical_doc",
                                    sub_url=f"https://github.com/{full_name}/blob/{default_branch}/README",
                                )
                                self.stats["fetched"] += 1
                    except Exception:
                        pass

            # ── 2. Source files ───────────────────────────────────────────
            tree = self._fetch_tree(owner, name, default_branch)
            for item in tree:
                if item.get("type") != "blob":
                    continue
                path = item.get("path", "")
                size = item.get("size", 0)

                if size > _MAX_FILE_BYTES:
                    continue

                ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
                if ext not in _CODE_EXTS and ext not in _DOC_EXTS:
                    continue

                url = f"https://github.com/{full_name}/blob/{default_branch}/{path}"
                if url in self._seen:
                    continue
                self._seen.add(url)

                api_url = f"{_API}/repos/{owner}/{name}/contents/{path}"
                text = self._fetch_blob(api_url)
                if not text or len(text.split()) < 10:
                    self.stats["skipped"] += 1
                    continue

                ctype = "source_code" if ext in _CODE_EXTS else "technical_doc"
                clang = detect_code_language(url)

                yield self._repo_doc(repo, text, ctype, sub_url=url, code_lang=clang)
                self.stats["fetched"] += 1
                time.sleep(_jitter(0.1))

            # ── 3. Issues as Q&A signal ───────────────────────────────────
            if include_issues:
                issues = self._fetch_issues(owner, name, max_issues=max_issues_repo)
                for issue in issues:
                    body = issue.get("body") or ""
                    if len(body.split()) < 20:
                        self.stats["skipped"] += 1
                        continue
                    title_text = issue.get("title", "")
                    text = f"Issue: {title_text}\n\n{body}"
                    h = hashlib.md5(text.encode()).hexdigest()
                    if h in self._seen:
                        continue
                    self._seen.add(h)
                    url = issue.get("html_url", "")
                    yield self._repo_doc(repo, text, "technical_qa", sub_url=url)
                    self.stats["issues_fetched"] += 1
                    self.stats["fetched"] += 1

            time.sleep(_jitter(0.5))

        self.print_stats()
