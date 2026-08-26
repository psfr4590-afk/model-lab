# Git Initialization Plan — Model Lab

**Status:** PLAN ONLY — no Git commands have been run.  
**Root:** `C:\Users\krash\Desktop\Training Bullshit`  
**Prepared for:** John (krash)

This document describes what to track, what to ignore, a proposed `.gitignore`, a
pre-initialization safety checklist, and the exact commands to run once approved.
**Nothing in this file runs anything. No `.git` folder exists. No commits exist.**

---

## 1. What Should Be Tracked

The following categories of files should be version-controlled:

### Python source
- `*.py` files throughout `pipeline/`, `command_center/`, `ui/`, `scripts/`
- Root-level entrypoints: `launch.py`, `run_pipeline.py`, `run_command_center.py`,
  `bootstrap.py`, `__init__.py`

### PowerShell scripts
- `scripts/preflight.ps1`
- `scripts/run_release_verification.ps1`

### Tests
- `tests/` directory (all `.py` files)
- `pytest.ini`

### Documentation
- `README.md`, `START_HERE.md`, `PROJECT_STATE.md`
- `VERIFICATION.md`, `VERIFICATION_CHECKLIST.md`
- `ui/START_UI.md`
- `RELEASE_VERIFICATION_REPORT.md` (this session's output)
- `GIT_INITIALIZATION_PLAN.md` (this file)

### YAML configuration templates
- `config/cleaner_config.yaml`
- `config/pipeline_config.yaml`
- `config/dataset_groups.yaml`
- `config/source_weights.yaml`
- `config/seed_urls.txt`
- `cleaner_config.yaml` (root-level copy)
- `pipeline_config.yaml` (root-level copy)
- `dataset_groups.yaml` (root-level copy)
- `source_weights.yaml` (root-level copy)

### Example / template environment files
- `.env.example` (root)
- `config/.env.example`
- `config/credentials.example.yaml`

### Project metadata
- `requirements.txt`


---

## 2. What Should Be Ignored

| Category | Pattern(s) |
|---|---|
| Python bytecode | `__pycache__/`, `*.py[cod]`, `*.pyo` |
| Pytest cache | `.pytest_cache/` |
| Ruff cache | `.ruff_cache/` |
| Runtime state | `.runtime/` |
| Dataset directories | `datasets/` |
| Pipeline output | `output/` |
| Scratch space | `scratch/` |
| Log files | `*.log` |
| Environment secrets | `.env` |
| Credential config | `config/credentials.yaml`, `credentials.yaml` |
| Model checkpoints | `datasets/**/checkpoints/`, `datasets/**/model/` |
| Training artifacts | `datasets/**/tokenized/`, `datasets/**/shards/`, `datasets/**/weighted/` |
| Raw crawled data | `datasets/**/raw/`, `datasets/**/cleaned/`, `datasets/**/dedup/` |
| Pipeline working dirs | `datasets/**/scratch/`, `datasets/**/errors/`, `datasets/**/metrics/` |
| Manifest / event logs | `datasets/**/events.jsonl`, `datasets/**/manifest.jsonl` |
| Editor noise | `.vscode/`, `.idea/`, `*.swp`, `*~` |
| OS noise | `.DS_Store`, `Thumbs.db`, `desktop.ini` |
| Audit output text | `scripts/_audit_out.txt`, `scripts/_probe_out.txt` |
| Bak files | `*.bak` *(see §4 — must be explicitly decided before staging)* |

---

## 3. Proposed `.gitignore` Body

The following content should be written to `.gitignore` at the repository root
**after user review and approval**. Do not write this file until §4 is resolved.

```gitignore
# === Python ===
__pycache__/
*.py[cod]
*.pyo

# === Test / lint caches ===
.pytest_cache/
.ruff_cache/

# === Runtime state ===
.runtime/

# === Datasets (data, models, artifacts — do not version) ===
datasets/

# === Pipeline output ===
output/

# === Scratch space ===
scratch/

# === Logs ===
*.log

# === Secrets and credentials ===
.env
config/credentials.yaml
credentials.yaml

# === Audit script output ===
scripts/_audit_out.txt
scripts/_probe_out.txt

# === Backup artifacts (decide before first commit) ===
*.bak

# === Editor noise ===
.vscode/
.idea/
*.swp
*~

# === OS noise ===
.DS_Store
Thumbs.db
desktop.ini
```


---

## 4. Pre-Initialization Safety Checklist

Complete every item before running `git init` or `git add`.

- [ ] **Review generated artifacts.**
  Confirm `RELEASE_VERIFICATION_REPORT.md` and `GIT_INITIALIZATION_PLAN.md` look correct
  and should be included in version control.

- [ ] **Review for secrets in source.**
  Grep or scan Python files for hardcoded API keys, tokens, passwords, or URLs
  that should not be public. Pay special attention to `command_center/secrets.py`
  and `command_center/config.py`.

- [ ] **Confirm credentials are absent from tracked files.**
  `config/credentials.yaml` (the live file, not the `.example`) must be absent or
  excluded. Confirm `.env` (the live file, not `.env.example`) is excluded.

- [ ] **Confirm intended YAML files are templates.**
  `config/credentials.example.yaml` and `config/.env.example` should contain only
  placeholder values, not real secrets.

- [ ] **Decide on `.bak` file policy.**
  Two `.bak` files exist:
  - `ui/screens/__init__.py.bak` — contains historical mojibake (`MÂ²S`).
  - `ui/screens/__init__.py.bak.20260817_094313` — timestamped backup.

  Options:
  - **Exclude** (recommended): keep `*.bak` in `.gitignore`. Historical artifact only.
  - **Include**: remove `*.bak` from `.gitignore` and stage with an explanatory commit note.

- [ ] **Decide on data, model, and output retention policy.**
  `datasets/` contains raw data, checkpoints, tokenized shards, and training artifacts.
  These are almost certainly too large for Git and should remain in `.gitignore`.
  Confirm this is the intended policy. If any dataset config JSON files
  (`dataset.json`, `dataset_config.json`) should be versioned, add targeted
  inclusions to `.gitignore` (e.g., `!datasets/**/dataset_config.json`).

- [ ] **Confirm `pipeline/datasets/` and `pipeline/release/` are intentionally empty.**
  These directories exist but appear to have no source files. Verify they should not
  contain `.gitkeep` files to preserve the directory structure in Git.

---

## 5. Proposed Commands for User-Approved Execution

Run these **in order** only after completing §4. Each step requires confirmation.

```powershell
# Step 1 — Initialize the repository
cd "C:\Users\krash\Desktop\Training Bullshit"
git init

# Step 2 — Write the .gitignore (content from §3 above)
# Create .gitignore with the proposed body before proceeding.

# Step 3 — Stage with review
git add --dry-run .
# Review the output. Confirm no secrets, datasets, or large artifacts appear.

# Step 4 — Check status before committing
git status

# Step 5 — Commit (only after reviewing git status output)
git commit -m "chore: establish canonical Model Lab baseline"
```


---

## 6. Suggested Initial Commit Message

```
chore: establish canonical Model Lab baseline

- No prior Git history exists; this is the first commit.
- pretrain-pipeline/ path references fully removed from live code.
- BackendManager wired to root-level run_command_center.py.
- Encoding (mojibake) repaired across all live source and YAML.
- 81 tests passing, 1 pre-existing warning.
- Command Center API verified (system, groups, datasets → HTTP 200).
- GUI launch verified (launch.py exit 0).
- .bak files excluded per ignore policy.
- datasets/, output/, scratch/, .runtime/ excluded per ignore policy.
```

---

## Notes

- The `scripts/` directory contains a mix of production PowerShell tooling and
  one-time Python repair scripts (`_fix_*.py`, `_repair_*.py`, `_audit_*.py`, etc.).
  All are tracked — they are part of the project history even if not regularly executed.
- The `pipeline/` directory contains two parallel crawler implementations
  (`pipeline/crawler/` and `pipeline/crawling/`). Both are tracked as-is.
- Root-level YAML files (`cleaner_config.yaml`, `pipeline_config.yaml`,
  `dataset_groups.yaml`, `source_weights.yaml`) appear to be copies of files in
  `config/`. Both locations are tracked; confirm this duplication is intentional.

---

*This plan was generated automatically. No Git commands have been executed.*
*No source, application, test, or configuration behavior has been changed.*
