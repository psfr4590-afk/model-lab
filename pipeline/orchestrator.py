"""
orchestrator.py — Wires all pipeline stages together.

Stage flow:
  crawl → clean → embed_dedup → weight → tokenize → shard

Each stage reads/writes JSONL in scratch/ and can be resumed independently.
Run with --stage=all or --stage=crawl|clean|dedup|weight|tokenize|shard.
"""

from __future__ import annotations

import json
import hashlib
import re
import logging
import os
import time
from pathlib import Path
from typing import Iterator

import yaml

from pipeline.types import Document
from pipeline.integrity import atomic_jsonl_write, artifact_valid, write_manifest
from pipeline.crawler.source_scorer import DomainSignalTracker, SourceWeightLookup
from pipeline.crawler.web_crawler    import WebCrawler
from pipeline.crawler.github_crawler import GitHubCrawler
from pipeline.crawler.arxiv_crawler  import ArxivCrawler
from pipeline.crawler.huggingface_crawler import HuggingFaceCrawler
from pipeline.crawler.google_crawler import GoogleCrawler
from pipeline.cleaner.cleaner        import Cleaner
from pipeline.embedder.semantic_dedup import SemanticDeduplicator
from pipeline.weighter.weighter      import DomainWeighter, reclassify_content_type
from pipeline.tokenizer.train_tokenizer import BPETokenizerTrainer
from pipeline.shardwriter.shard_writer  import ShardWriter
from pipeline.trainer.train             import Trainer

log = logging.getLogger("orchestrator")


def _setup_logging(out_dir: Path, level: str = "INFO"):
    log_dir = out_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(name)s] [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%dT%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    if not any(getattr(h, "_pretrain_console", False) for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        sh._pretrain_console = True
        root.addHandler(sh)
    log_file = (log_dir / "pipeline.log").resolve()
    if not any(getattr(h, "_pretrain_file", None) == str(log_file) for h in root.handlers):
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        fh._pretrain_file = str(log_file)
        root.addHandler(fh)


def _load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _jsonl_write(docs: Iterator[Document], path: Path, kind: str = "jsonl"):
    def producer():
        for doc in docs:
            yield doc.to_jsonl()
    count = atomic_jsonl_write(path, producer)
    write_manifest(path, kind=kind, rows=count)
    log.info(f"Wrote {count} docs → {path} | sha256 manifest committed")
    return count


def _jsonl_read(path: Path) -> Iterator[Document]:
    if not path.exists():
        raise FileNotFoundError(f"Required pipeline input does not exist: {path}")
    bad = 0
    max_bad = 0
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                if not isinstance(d, dict):
                    raise TypeError("record is not an object")
                yield Document.from_dict(d)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                bad += 1
                log.error(f"Invalid JSONL record {path}:{line_no}: {exc}")
                if bad > max_bad:
                    raise RuntimeError(f"Input integrity failure: {bad} malformed records in {path}") from exc
    if bad:
        log.warning(f"Skipped {bad} malformed records from {path}")


class Pipeline:

    def __init__(self, config_path: str = "config/pipeline_config.yaml", dataset_id: int | None = None):
        self._cfg_path = config_path
        self._project_root = Path(config_path).resolve().parent.parent
        self.cfg       = _load_config(config_path)
        self.dataset_id = dataset_id

        name       = self.cfg["pipeline"].get("name", "pipeline")
        out_dir    = Path(self.cfg["pipeline"].get("output_dir",  "output"))
        scratch    = Path(self.cfg["pipeline"].get("scratch_dir", "scratch"))

        # Dataset sessions are fully isolated.  The legacy project-level output/scratch
        # paths remain available when no dataset_id is supplied for backwards compatibility.
        if dataset_id is not None:
            self._dataset_root = self._project_root / "datasets" / f"dataset_{dataset_id:03d}"
            if not self._dataset_root.exists():
                raise FileNotFoundError(f"Dataset session does not exist: {self._dataset_root}")
            out_dir = self._dataset_root / "output"
            scratch = self._dataset_root / "scratch"
        else:
            self._dataset_root = None
            out_dir = self._project_root / out_dir
            scratch = self._project_root / scratch

        self._out     = out_dir
        self._scratch = scratch
        self._out.mkdir(parents=True, exist_ok=True)
        self._scratch.mkdir(parents=True, exist_ok=True)

        # Re-root every mutable artifact path into this dataset session.
        # This is what makes Dataset 001 and Dataset 002 genuinely independent
        # training experiments rather than two labels pointing at one output tree.
        self.cfg.setdefault("pipeline", {})["output_dir"] = str(self._out)
        self.cfg["pipeline"]["scratch_dir"] = str(self._scratch)
        self.cfg.setdefault("tokenizer", {})["output_path"] = str(self._out / "tokenizer")
        self.cfg.setdefault("shard", {})["output_dir"] = str(self._out / "shards")
        self.cfg.setdefault("train", {})["shard_dir"] = str(self._out / "shards")
        self.cfg.setdefault("export", {})["llamacpp_dir"] = str(self._project_root / self.cfg.get("export", {}).get("llamacpp_dir", "llama.cpp"))

        _setup_logging(out_dir)
        log.info(f"Pipeline '{name}' initialized | config={config_path}")

        self._resume = self.cfg["pipeline"].get("resume", True)

        # Shared helpers
        weights_file = self._project_root / "config" / "source_weights.yaml"
        self._weights  = SourceWeightLookup(str(weights_file))
        self._signals  = DomainSignalTracker(self._weights.signal_gate_config())

    def _should_skip(self, path: Path, stage: str) -> bool:
        if self._resume and artifact_valid(path):
            log.info(f"[{stage}] Verified artifact exists, skipping: {path}")
            return True
        if self._resume and path.exists():
            log.warning(f"[{stage}] Existing artifact is unverified or corrupt; rebuilding: {path}")
        return False

    # ── Stage 1: Crawl ───────────────────────────────────────────────────────

    def _dataset_group_for_session(self) -> dict | None:
        if self.dataset_id is None:
            return None
        meta_path = self._dataset_root / "dataset.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"Missing dataset metadata: {meta_path}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        gid = meta.get("group_id")
        groups = self._load_dataset_groups()
        for group in groups:
            if group.get("id") == gid:
                return group
        custom = meta.get("group_config")
        if custom:
            return custom
        raise ValueError(f"Dataset {self.dataset_id} references unknown group '{gid}'")

    def _load_dataset_groups(self) -> list[dict]:
        path = self._project_root / self.cfg.get("crawl", {}).get("dataset_groups_file", "config/dataset_groups.yaml")
        if not path.exists():
            log.warning(f"No dataset_groups file at {path} — falling back to single ungrouped crawl")
            return [{"id": "default", "name": "default", "sources": self.cfg.get("crawl", {}).get("sources", {})}]
        with open(path, "r", encoding="utf-8") as f:
            groups = yaml.safe_load(f).get("dataset_groups", [])
        if not groups:
            log.warning(f"{path} has no dataset_groups defined")
        return groups

    def _merged_group_cfg(self, base_crawl_cfg: dict, group: dict) -> dict:
        """base crawl_cfg (shared auth/timeouts/allowlists) shallow-merged with this
        group's github/huggingface/google/web sub-configs — group keys (topics,
        datasets, queries, seed_urls, etc.) override/add to the shared defaults
        without dropping shared settings like token_env or url_allowlist_patterns."""
        merged = dict(base_crawl_cfg)
        for key in ("github", "huggingface", "google", "web", "arxiv"):
            merged[key] = {**base_crawl_cfg.get(key, {}), **group.get(key, {})}
        merged["sources"] = group.get("sources", base_crawl_cfg.get("sources", {}))
        return merged

    def _crawl_one_group(self, group: dict, base_crawl_cfg: dict) -> Path:
        gid = group.get("id", "default")
        out = self._scratch / ("01_crawled.jsonl" if self.dataset_id is not None else f"01_crawled__{gid}.jsonl")
        if self._should_skip(out, f"crawl:{gid}"):
            return out

        group_cfg = self._merged_group_cfg(base_crawl_cfg, group)
        stages    = group_cfg.get("sources", {})
        log.info(f"── Dataset group '{gid}' ({group.get('name', gid)}) ──")

        def group_docs() -> Iterator[Document]:
            if stages.get("web", True):
                log.info(f"[{gid}] Starting WebCrawler ...")
                wc = WebCrawler(group_cfg, self._weights, self._signals)
                for doc in wc.crawl():
                    doc.meta["dataset_group"] = gid
                    yield doc

            if stages.get("github", True):
                log.info(f"[{gid}] Starting GitHubCrawler ...")
                gh = GitHubCrawler(group_cfg, self._weights, self._signals)
                for doc in gh.crawl():
                    doc.meta["dataset_group"] = gid
                    yield doc

            if stages.get("arxiv", True):
                log.info(f"[{gid}] Starting ArxivCrawler ...")
                ax = ArxivCrawler(group_cfg, self._weights, self._signals)
                for doc in ax.crawl():
                    doc.meta["dataset_group"] = gid
                    yield doc

            if stages.get("huggingface", False):
                log.info(f"[{gid}] Starting HuggingFaceCrawler ...")
                hf = HuggingFaceCrawler(group_cfg, self._weights, self._signals)
                for doc in hf.crawl():
                    doc.meta["dataset_group"] = gid
                    yield doc

            if stages.get("google", False):
                log.info(f"[{gid}] Starting GoogleCrawler ...")
                gg = GoogleCrawler(group_cfg, self._weights, self._signals)
                for doc in gg.crawl():
                    doc.meta["dataset_group"] = gid
                    yield doc

        _jsonl_write(group_docs(), out)
        return out

    def stage_crawl(self, only_group: str | None = None):
        out = self._scratch / "01_crawled.jsonl"
        base_crawl_cfg = dict(self.cfg.get("crawl", {}))
        if base_crawl_cfg.get("web", {}).get("seed_urls_file"):
            base_crawl_cfg["web"] = dict(base_crawl_cfg.get("web", {}))
            base_crawl_cfg["web"]["seed_urls_file"] = str(self._project_root / base_crawl_cfg["web"]["seed_urls_file"])
        groups = self._load_dataset_groups()
        if self.dataset_id is not None and not only_group:
            session_group = self._dataset_group_for_session()
            groups = [session_group] if session_group else []
            only_group = session_group.get("id") if session_group else None

        if only_group:
            groups = [g for g in groups if g.get("id") == only_group]
            if not groups:
                raise ValueError(f"Unknown dataset group id: {only_group}")
            # Single-group runs don't touch the shared merged file — return the
            # group's own scratch file so you can crawl one at a time without
            # clobbering the others' already-merged output.
            return self._crawl_one_group(groups[0], base_crawl_cfg)

        group_paths = [self._crawl_one_group(g, base_crawl_cfg) for g in groups]
        if self.dataset_id is not None and group_paths:
            return group_paths[0]

        # Merge per-group files into the single file downstream stages consume.
        if self._should_skip(out, "crawl:merge"):
            return out
        count = 0
        with open(out, "w", encoding="utf-8") as fout:
            for gp in group_paths:
                if not gp.exists():
                    continue
                with open(gp, encoding="utf-8") as fin:
                    for line in fin:
                        if line.strip():
                            fout.write(line)
                            count += 1
        log.info(f"Merged {len(group_paths)} dataset group(s) → {count} total docs → {out}")
        log.info(f"Abandoned domains: {self._signals.abandoned_domains()}")
        return out

    # ── Stage 2: Clean ───────────────────────────────────────────────────────

    def stage_clean(self, in_path: Path) -> Path:
        out = self._scratch / "02_cleaned.jsonl"
        if self._should_skip(out, "clean"):
            return out

        if not artifact_valid(in_path):
            raise RuntimeError(f"Clean input failed integrity validation: {in_path}")
        cleaner = Cleaner(str(self._project_root / self.cfg.get("clean", {}).get("config_file", "config/cleaner_config.yaml")))
        kept = 0

        def clean_docs() -> Iterator[Document]:
            nonlocal kept
            for doc in _jsonl_read(in_path):
                # Reclassify content type if unknown
                doc.content_type = reclassify_content_type(doc)

                result = cleaner.clean(doc.text, doc_id=doc.doc_id)
                if result.kept:
                    doc.text         = result.text
                    doc.clean_action = result.action
                    doc.clean_score  = result.score
                    doc.word_count   = len(doc.text.split())
                    doc.char_count   = len(doc.text)
                    kept += 1
                    yield doc

        _jsonl_write(clean_docs(), out)
        cleaner.print_stats()
        return out

    # ── Stage 3: Semantic Dedup ──────────────────────────────────────────────

    def stage_embed_dedup(self, in_path: Path) -> Path:
        out = self._scratch / "03_deduped.jsonl"
        if self._should_skip(out, "embed_dedup"):
            return out

        if not artifact_valid(in_path):
            raise RuntimeError(f"Dedup input failed integrity validation: {in_path}")
        dedup_cfg = self.cfg.get("embed_dedup", {})
        deduper   = SemanticDeduplicator(dedup_cfg)
        buf_size  = int(dedup_cfg.get("buffer_size", 10_000))
        seen_exact: set[str] = set()
        exact_dropped = 0

        def deduped_stream() -> Iterator[Document]:
            nonlocal exact_dropped
            buf: list[Document] = []
            for doc in _jsonl_read(in_path):
                normalized = re.sub(r"\s+", " ", doc.text).strip().lower()
                h = hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()
                if h in seen_exact:
                    exact_dropped += 1
                    continue
                seen_exact.add(h)
                buf.append(doc)
                if len(buf) >= buf_size:
                    yield from deduper.run(buf)
                    buf.clear()
            if buf:
                yield from deduper.run(buf)

        _jsonl_write(deduped_stream(), out)
        log.info(f"Exact global dedup dropped {exact_dropped:,} records before semantic dedup")
        deduper.print_stats()
        return out

    # ── Stage 4: Weight ──────────────────────────────────────────────────────

    def stage_weight(self, in_path: Path) -> Path:
        out = self._scratch / "04_weighted.jsonl"
        if self._should_skip(out, "weight"):
            return out

        if not artifact_valid(in_path):
            raise RuntimeError(f"Weight input failed integrity validation: {in_path}")
        strategy = self.cfg.get("weight", {}).get("strategy", "upsample")
        weighter = DomainWeighter("config/source_weights.yaml", strategy=strategy)
        _jsonl_write(weighter.apply(_jsonl_read(in_path)), out)
        weighter.print_stats()
        return out

    # ── Stage 5: Tokenizer training ──────────────────────────────────────────

    def stage_tokenize(self, corpus_path: Path):
        tok_cfg  = self.cfg.get("tokenizer", {})
        tok_path = Path(tok_cfg.get("output_path", "output/tokenizer"))
        marker   = tok_path / "tokenizer.json"

        if self._should_skip(marker, "tokenize"):
            trainer = BPETokenizerTrainer(tok_cfg)
            return trainer.load()

        if not artifact_valid(corpus_path):
            raise RuntimeError(f"Tokenizer input failed integrity validation: {corpus_path}")
        trainer = BPETokenizerTrainer(tok_cfg)
        tok     = trainer.train(corpus_path)
        write_manifest(marker, kind="tokenizer", extra={"vocab_size": tok.get_vocab_size()})
        return tok

    # ── Stage 6: Shard ──────────────────────────────────────────────────────

    def stage_shard(self, corpus_path: Path, tokenizer) -> Path:
        shard_cfg = self.cfg.get("shard", {})
        shard_dir = Path(shard_cfg.get("output_dir", "output/shards"))

        marker = shard_dir / "shards.manifest.json"
        if self._resume and marker.exists():
            try:
                m = json.loads(marker.read_text(encoding="utf-8"))
                files = [shard_dir / x for x in m.get("files", [])]
                if files and all(f.exists() and f.stat().st_size > 0 for f in files):
                    log.info(f"[shard] Verified {len(files)} shards, skipping")
                    return shard_dir
            except Exception:
                log.warning("[shard] Invalid shard manifest; rebuilding")
        # Never mix a new shard build with stale files.
        for old in shard_dir.glob("shard_*.bin"):
            old.unlink(missing_ok=True)

        writer = ShardWriter(shard_cfg, tokenizer)
        writer.write(corpus_path)
        files = sorted(p.name for p in shard_dir.glob("shard_*.bin"))
        if not files:
            raise RuntimeError("Shard stage produced no shard files")
        marker.write_text(json.dumps({"schema": 1, "files": files, "source": str(corpus_path)}, indent=2), encoding="utf-8")
        return shard_dir

    # ── Full run ─────────────────────────────────────────────────────────────

    # ── Stage 7: Train ──────────────────────────────────────────────────────

    def stage_train(self) -> Path:
        """Run training loop. Returns path to best checkpoint."""
        ckpt_dir = self._out / "checkpoints"
        # Check for final checkpoint
        finals = list(ckpt_dir.glob("ckpt_final_*.pt"))
        if self._resume and finals:
            log.info(f"[train] Final checkpoint exists, skipping: {sorted(finals)[-1]}")
            return sorted(finals)[-1]

        train_cfg = self.cfg.get("train", {})
        if not __import__("torch").cuda.is_available() and not bool(train_cfg.get("allow_cpu_training", False)):
            raise RuntimeError("CUDA is unavailable and allow_cpu_training=false. Refusing accidental CPU pretraining; set train.allow_cpu_training=true or use bootstrap's CPU-safe model settings.")
        trainer = Trainer(self.cfg)
        trainer.run()
        best = sorted(ckpt_dir.glob("ckpt_best_*.pt"))
        return best[-1] if best else sorted(ckpt_dir.glob("ckpt_*.pt"))[-1]

    # ── Stage 8: Export ─────────────────────────────────────────────────────

    def stage_export(self):
        """Convert best checkpoint → HF → GGUF → quantize → Modelfile."""
        gguf_dir = self._out / "gguf"
        model_name = self.cfg.get("export", {}).get("model_name", "pretrain-model")
        mf = gguf_dir / "Modelfile"
        if self._resume and mf.exists():
            log.info("[export] Modelfile exists, skipping")
            return

        # Import and call export directly without mutating sys.argv
        import sys as _sys
        from scripts.export_gguf import main as export_main
        exp_cfg = self.cfg.get("export", {})
        _saved_argv = _sys.argv
        try:
            _sys.argv = [
                "export_gguf.py",
                "--output-dir",   str(self._out),
                "--llamacpp-dir", str(self._project_root / exp_cfg.get("llamacpp_dir", "llama.cpp")),
                "--quant",        exp_cfg.get("quant", "Q4_K_M"),
                "--model-name",   model_name,
            ]
            export_main()
        finally:
            _sys.argv = _saved_argv

    def run(self, stages: str = "all", dataset_group: str | None = None):
        if self.dataset_id is not None and dataset_group is None:
            group = self._dataset_group_for_session()
            dataset_group = group.get("id") if group else None
        enabled = self.cfg.get("stages", {})
        t0 = time.time()

        do_all    = stages == "all"
        do_crawl  = do_all or stages == "crawl"
        do_clean  = do_all or stages == "clean"
        do_dedup  = do_all or stages == "dedup"
        do_weight = do_all or stages == "weight"
        do_tok    = do_all or stages == "tokenize"
        do_shard  = do_all or stages == "shard"
        do_train  = do_all or stages == "train"
        do_export = do_all or stages == "export"

        suffix = "" if self.dataset_id is not None else (f"__{dataset_group}" if dataset_group else "")
        crawled_path  = self._scratch / f"01_crawled{suffix}.jsonl"
        cleaned_path  = self._scratch / f"02_cleaned{suffix}.jsonl"
        deduped_path  = self._scratch / f"03_deduped{suffix}.jsonl"
        weighted_path = self._scratch / f"04_weighted{suffix}.jsonl"

        if do_crawl and enabled.get("crawl", True):
            crawled_path = self.stage_crawl(only_group=dataset_group)
        elif not crawled_path.exists() and dataset_group:
            raise RuntimeError(f"Dataset-group input missing: {crawled_path}. Run crawl for group '{dataset_group}' first.")
        elif not crawled_path.exists() and any((do_clean, do_dedup, do_weight, do_tok, do_shard)):
            raise RuntimeError(f"Crawl artifact missing: {crawled_path}. Run crawl first or provide the correct dataset group.")

        if do_clean and enabled.get("clean", True):
            cleaned_path = self.stage_clean(crawled_path)

        if do_dedup and enabled.get("embed_dedup", True):
            deduped_path = self.stage_embed_dedup(cleaned_path)

        if do_weight and enabled.get("weight", True):
            weighted_path = self.stage_weight(deduped_path)

        tokenizer = None
        if do_tok and enabled.get("tokenize", True):
            if dataset_group and self.dataset_id is None:
                tok_cfg = dict(self.cfg.get("tokenizer", {}))
                tok_cfg["output_path"] = str(self._out / "tokenizer" / dataset_group)
                original = self.cfg.get("tokenizer", {})
                self.cfg["tokenizer"] = tok_cfg
                try:
                    tokenizer = self.stage_tokenize(weighted_path)
                finally:
                    self.cfg["tokenizer"] = original
            else:
                tokenizer = self.stage_tokenize(weighted_path)

        if do_shard and enabled.get("shard", True):
            # If tokenize stage didn't run (e.g. --stages shard), try loading
            # an existing tokenizer from disk so shard doesn't silently no-op.
            if tokenizer is None:
                tok_cfg  = dict(self.cfg.get("tokenizer", {}))
                if dataset_group and self.dataset_id is None:
                    tok_cfg["output_path"] = str(self._out / "tokenizer" / dataset_group)
                tok_path = Path(tok_cfg.get("output_path", "output/tokenizer")) / "tokenizer.json"
                if tok_path.exists() and artifact_valid(tok_path):
                    trainer  = BPETokenizerTrainer(tok_cfg)
                    tokenizer = trainer.load()
                    log.info(f"[shard] Loaded verified tokenizer from {tok_path}")
                else:
                    raise RuntimeError(f"[shard] No verified tokenizer found at {tok_path}; run tokenize first")
            if tokenizer is not None:
                if dataset_group and self.dataset_id is None:
                    shard_cfg = dict(self.cfg.get("shard", {}))
                    shard_cfg["output_dir"] = str(self._out / "shards" / dataset_group)
                    original = self.cfg.get("shard", {})
                    self.cfg["shard"] = shard_cfg
                    try:
                        self.stage_shard(weighted_path, tokenizer)
                    finally:
                        self.cfg["shard"] = original
                else:
                    self.stage_shard(weighted_path, tokenizer)

        if do_train and enabled.get("train", True):
            train_cfg = dict(self.cfg.get("train", {}))
            train_cfg["shard_dir"] = str(self._out / "shards" / dataset_group) if (dataset_group and self.dataset_id is None) else str(self._out / "shards")
            original_train = self.cfg.get("train", {})
            self.cfg["train"] = train_cfg
            try:
                self.stage_train()
            finally:
                self.cfg["train"] = original_train

        if do_export and enabled.get("export", True):
            self.stage_export()

        elapsed = time.time() - t0
        log.info(f"Pipeline complete in {elapsed/60:.1f}m")
