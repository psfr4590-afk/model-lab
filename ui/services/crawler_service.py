"""
crawler_service.py — Backend bridge for the Crawler screen.

Exposes:
  processes()       — list of live OS crawler processes (PowerShell)
  start(did)        — POST /api/datasets/{did}/stage/crawl
  stop(did)         — POST /api/datasets/{did}/stop
  state(did)        — GET  /api/datasets/{did}
  stats(did)        — GET  /api/datasets/{did}/crawl/stats   (per-source counters)
  domain_signals(did) — GET /api/datasets/{did}/crawl/domains (rolling signal scores)
  log_tail(did, n)  — GET  /api/datasets/{did}/crawl/log?tail=N
"""

from __future__ import annotations

import subprocess
from ..core import registry


class CrawlerService:

    # ── OS-level process inspection ─────────────────────────────────────────

    def processes(self) -> str:
        cmd = (
            "Get-CimInstance Win32_Process "
            "| Where-Object {"
            "  $_.CommandLine -and "
            "  $_.CommandLine -match 'web_crawler|github_crawler|arxiv_crawler|huggingface_crawler|google_crawler|run_pipeline'"
            "} "
            "| Select-Object ProcessId,Name,WorkingSetSize,CommandLine "
            "| Format-List"
        )
        try:
            p = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True, text=True, timeout=15,
            )
            out = p.stdout.strip()
            return out if out else "No crawler processes detected."
        except Exception as e:
            return f"Process inspection unavailable: {e}"

    # ── Pipeline API calls ──────────────────────────────────────────────────

    def start(self, did: str | int) -> dict:
        return registry.process().post(f"/api/datasets/{did}/stage/crawl")

    def stop(self, did: str | int) -> dict:
        return registry.process().post(f"/api/datasets/{did}/stop")

    def state(self, did: str | int) -> dict:
        return registry.process().get(f"/api/datasets/{did}")

    def stats(self, did: str | int) -> dict:
        """
        Returns dict keyed by source name, each with counters:
          { "web": {"fetched": N, "skipped": N, "errors": N, "abandoned_domains": N,
                    "trafilatura_used": N, "bs4_fallback": N, "lang_rejected": N,
                    "sitemaps_discovered": N, "running": bool},
            "github":  {..., "issues_fetched": N},
            "arxiv":   {..., "citations_enriched": N, "pdf_extracted": N},
            "huggingface": {...},
            "google":  {...} }
        Falls back to empty dict if the endpoint doesn't exist yet.
        """
        try:
            result = registry.process().get(f"/api/datasets/{did}/crawl/stats")
            if isinstance(result, dict):
                return result
        except Exception:
            pass
        return {}

    def domain_signals(self, did: str | int) -> list[tuple[str, float, int]]:
        """
        Returns a list of (domain, avg_score, page_count) sorted by avg_score desc.
        Falls back to empty list if the endpoint doesn't exist yet.
        """
        try:
            result = registry.process().get(f"/api/datasets/{did}/crawl/domains")
            if isinstance(result, list):
                return [(r.get("domain", ""), float(r.get("avg_score", 0)),
                         int(r.get("count", 0))) for r in result]
        except Exception:
            pass
        return []

    def log_tail(self, did: str | int, n: int = 80) -> list[str]:
        """
        Returns last N lines of the crawl log for this dataset.
        Falls back to empty list.
        """
        try:
            result = registry.process().get(f"/api/datasets/{did}/crawl/log", params={"tail": n})
            if isinstance(result, list):
                return [str(line) for line in result]
            if isinstance(result, str):
                return result.splitlines()[-n:]
        except Exception:
            pass
        return []
