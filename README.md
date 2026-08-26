# Model Lab

**Model Lab** is the package name for the **M²S Model Training Pipeline** command center.

The desktop application is a local control surface over the existing localhost FastAPI command center and pretraining pipeline. It does not implement a second copy of the pipeline.

## Launch

Windows:

```powershell
pip install -r .\requirements.txt
python .\launch.py
```

The desktop UI starts the existing local backend when needed and is designed for a **1760×990** display.

## Navigation

Model Lab exposes:

- Dashboard
- Datasets
- Pipeline
- Credentials
- Sources
- Crawler
- Training
- Outputs
- Logs
- System
- Configuration
- Diagnostics
- Command Center

Dataset sessions are independently navigable. The pipeline stages are **Crawl → Clean → Semantic Dedup → Weight → Tokenize → Shard → Train → Export**.

## Seeded datasets

The first four configured groups are:

1. `swe_cs_systems` — Software Engineering + Computer Science + Systems Engineering.
2. `ai_ml_cybersec_dataeng` — AI/ML + Cybersecurity + Data Engineering.
3. `sci_reasoning_forensics_formal` — Scientific Reasoning + Digital Forensics + Formal Methods.
4. `domain_finance_bio_robotics` — Finance + Biology + Robotics + other domain-specific knowledge.

They become Dataset 001–004 when seeded. Additional sessions can be created from the UI.

## Credentials

Four credential slots are preconfigured:

| Provider | Environment variable |
|---|---|
| GitHub | `GITHUB_TOKEN` |
| Hugging Face | `HF_TOKEN` |
| Google API key | `GOOGLE_API_KEY` |
| Google Search engine ID | `GOOGLE_CX` |

The existing encrypted credential store is authoritative. Secret values are never returned by credential list operations. On Windows it uses DPAPI. The non-Windows fallback uses Fernet and `PIPELINE_CREDENTIAL_KEY`.

The credential test checks local storage/decryption only; it does not contact the provider.

## Pipeline

The existing pipeline performs crawling, cleaning, semantic deduplication, weighting, tokenization, sharding, training, and GGUF export. Model Lab starts those real backend operations for the selected dataset instead of simulating them.

### Crawler upgrades (v1.2)

| Feature | Component | Notes |
|---|---|---|
| Sitemap discovery | WebCrawler | Auto-probes `sitemap.xml` per seed domain for additional URLs |
| Trafilatura extraction | WebCrawler | Best-in-class boilerplate removal; graceful bs4 fallback |
| English-only gating | WebCrawler | `english_only: true` — requires `pip install langdetect` |
| Jitter backoff | WebCrawler, GitHubCrawler | Randomised ±25% delay prevents deterministic fingerprinting |
| HTTP 429 / Retry-After | WebCrawler, GitHubCrawler | Respects server rate-limit signals explicitly |
| Issue Q&A harvesting | GitHubCrawler | Closed issues as technical Q&A signal (`include_issues: true`) |
| Citation enrichment | ArxivCrawler | Semantic Scholar citation counts, no API key needed |
| Citation weight boost | ArxivCrawler | Log-scale bump to `final_weight` for highly-cited papers |
| Expanded reward/penalty patterns | source_scorer | `et al.`, test keywords, API terms; privacy policy penalty |
| Crawler UI panels | Model Lab desktop | Per-source counters, domain signal scores, extraction stats, log tail |

## Configuration

The authoritative configuration remains under `config/`:

- `pipeline_config.yaml`
- `dataset_groups.yaml`
- `cleaner_config.yaml`
- `source_weights.yaml`
- `seed_urls.txt`

## Runtime

The hardened runtime and doctor remain available:

```powershell
python .\run_pipeline.py --doctor
```

CUDA, NVIDIA drivers, external API access, network conditions, and native llama.cpp conversion remain target-machine dependent.

## Direct backend launch

For backend/browser-only operation:

```powershell
python .\run_command_center.py
```

The backend defaults to localhost (`127.0.0.1:8000`).

## Verification

The Model Lab package includes the existing command-center/runtime test suite. Vendor tests inside the bundled `llama.cpp` tree are intentionally outside the Model Lab pytest scope.

## Verification

Model Lab includes a dedicated release verification suite under `tests/model_lab/`. It verifies structural contracts and service behavior without requiring live external services, and includes target-machine checks for Windows, Tk, the 1760×990 display target, local Command Center health, the hardened doctor, and desktop UI construction/navigation.

Run the automated suite with:

```powershell
python -m pytest -q
```

Run the target-machine checks on the actual Windows installation with:

```powershell
python -m pytest -q .\tests\model_lab\test_machine_environment.py
```

The full release procedure is documented in `VERIFICATION_CHECKLIST.md` and `scripts/run_release_verification.ps1`. Human-visible UI checks remain required because automated headless tests cannot certify visual usability.
