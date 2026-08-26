# Model Lab — Project State

**Last updated:** 2026-08-18
**Version:** 1.2.0

## Identity

- Package: **Model Lab**
- System: **M²S Model Training Pipeline**
- Launcher: `launch.py`
- UI target: 1760×990
- Backend: existing localhost FastAPI command center (root-level `run_command_center.py`)
- Pipeline stages: crawl → clean → dedup → weight → tokenize → shard → train → export

## Seeded dataset groups

| ID | Domain |
|---|---|
| `swe_cs_systems` | Software Engineering + CS + Systems |
| `ai_ml_cybersec_dataeng` | AI/ML + Cybersecurity + Data Engineering |
| `sci_reasoning_forensics_formal` | Scientific Reasoning + Forensics + Formal Methods |
| `domain_finance_bio_robotics` | Finance + Biology + Robotics |

## Credentials

`GITHUB_TOKEN`, `HF_TOKEN`, `GOOGLE_API_KEY`, `GOOGLE_CX`

## Architecture note

The desktop UI is a control surface — no second pipeline implementation. Dataset state, stage execution, credentials, and runtime behavior are owned by the existing backend.

---

## Current crawler state (v1.2.0)

### WebCrawler
- STATUS: IMPLEMENTED, CONTRACT-TESTED (tests 01–08, 26–30), UNVERIFIED live
- Trafilatura-first extraction; bs4 fallback when not installed
- Sitemap discovery per seed domain
- English-only gating via langdetect (optional)
- Jitter backoff; 429 Retry-After handling
- SHA-256 dedup; robots.txt; domain signal gating

### GitHubCrawler
- STATUS: IMPLEMENTED, CONTRACT-TESTED (tests 09–12, 31–33), UNVERIFIED live
- Closed-issue Q&A harvesting (`include_issues`, `max_issues_per_repo`)
- Jitter backoff; 429 Retry-After handling
- Star-count log-scale weight bonus retained

### ArxivCrawler
- STATUS: IMPLEMENTED, CONTRACT-TESTED (tests 13–14, 34), UNVERIFIED live
- Semantic Scholar citation enrichment (`enrich_citations: true`, no key needed)
- Citation-count log-scale weight boost added to final_weight
- PDF text extraction still optional (pdfminer.six)

### HuggingFaceCrawler
- STATUS: IMPLEMENTED, CONTRACT-TESTED (test 15), UNVERIFIED live
- Unchanged from v1.0 in this session

### GoogleCrawler
- STATUS: IMPLEMENTED, CONTRACT-TESTED (config tests), UNVERIFIED live
- Unchanged from v1.0 in this session

### source_scorer
- STATUS: IMPLEMENTED, CONTRACT-TESTED (test 35)
- Reward patterns: 13 (was 6) — added et al., ML metrics, test keywords, ArXiv ID
- Penalty patterns: 12 (was 7) — added privacy policy, buy/cart, symbol spam, repetition spam

---

## UI state

### Crawler screen (ui/screens/crawler.py)
- STATUS: IMPLEMENTED, UNVERIFIED live (requires running backend)
- Panels: per-source counters, extraction stats, domain signal scores, log tail, process list
- Service methods: `stats()`, `domain_signals()`, `log_tail()` — graceful no-op if backend endpoints absent

---

## Test state

| Suite | Tests | Status |
|---|---|---|
| test_crawler_20_point_audit.py | 35 | 35 PASSED (2026-08-18) |

---

## Known limitations / open items

- OBSERVATION: Semantic Scholar `enrich_citations` adds ~0.6s/paper to ArXiv crawl. Config flag `enrich_citations: false` disables it for speed.
- OBSERVATION: `english_only` gating requires `pip install langdetect`. If not installed, gating is silently skipped (permissive fallback).
- OBSERVATION: Trafilatura is an optional install (`pip install trafilatura`). If absent, falls back to bs4 — which is already the prior behavior.
- KNOWN GAP: openreview.net domain trap (flagged in prior audit) — still unresolved.
- KNOWN GAP: semantic dedup buffer boundary gap — still unresolved.
- KNOWN GAP: deprecated PyTorch AMP API — still unresolved.
- KNOWN GAP: SSRF protection in GoogleCrawler — still unresolved.
- KNOWN GAP: Crawler UI stat panels require backend API endpoints (`/crawl/stats`, `/crawl/domains`, `/crawl/log`) not yet implemented in the FastAPI command center. Panels degrade gracefully to empty state.
- NOT VERIFIED: All live crawl behavior — all tests are contract/static-analysis only. No real HTTP requests made.
- NOT VERIFIED: UI rendering on target 1760×990 display — requires human visual inspection.

## Next logical actions

1. (Optional) `pip install trafilatura langdetect` to activate upgraded extraction
2. Implement `/api/datasets/{did}/crawl/stats`, `/crawl/domains`, `/crawl/log` in FastAPI command center to feed the new UI panels with live data
3. Resolve remaining audit findings: openreview.net trap, semantic dedup buffer gap, PyTorch AMP deprecation, SSRF in GoogleCrawler
4. Run a live crawl test on a small dataset to verify trafilatura extraction quality vs prior bs4 output
