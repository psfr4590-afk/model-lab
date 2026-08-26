#!/usr/bin/env python3
"""CLI entry point for the pretrain data pipeline.

The entry point discovers its project root from its own location, so it can be
launched from any working directory. Pipeline execution uses the interpreter
that launched this process and the repository's canonical project layout.
"""
from __future__ import annotations

import argparse
import os
import sys

# Windows PowerShell/cmd may expose a legacy CP1252 stdout.
# The CLI emits Unicode stage descriptions, so prefer UTF-8 when supported.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STAGES = ["crawl", "clean", "dedup", "weight", "tokenize", "shard", "train", "export"]

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pretraining data pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", default="config/pipeline_config.yaml")
    parser.add_argument("--stages", default="all")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--dataset-group", default=None)
    parser.add_argument(
        "--dataset-id",
        type=int,
        default=None,
        help="Run the entire pipeline inside datasets/dataset_NNN as an isolated session",
    )
    parser.add_argument("--list-groups", action="store_true")
    parser.add_argument("--list-stages", action="store_true")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Launch the local FastAPI project command center",
    )
    args = parser.parse_args()

    if args.list_stages:
        print("Available stages:")
        descs = {
            "crawl": "Crawl web, GitHub, ArXiv → 01_crawled.jsonl",
            "clean": "HTML/unicode/refusal filter → 02_cleaned.jsonl",
            "dedup": "Semantic near-dedup → 03_deduped.jsonl",
            "weight": "Apply domain/content weights → 04_weighted.jsonl",
            "tokenize": "Train BPE tokenizer → output/tokenizer/",
            "shard": "Tokenize + write binary shards → output/shards/",
            "train": "Train Llama model with AMP + checkpointing → output/checkpoints/",
            "export": "Export best checkpoint → HF → GGUF → Ollama Modelfile",
        }
        for stage, desc in descs.items():
            print(f"  {stage:<12} {desc}")
        return 0

    os.chdir(ROOT)
    if args.web:
        try:
            import uvicorn
            from command_center.config import load_pipeline_config
            ccfg = load_pipeline_config().get("command_center", {})
            uvicorn.run("command_center.web:app", host=ccfg.get("host", "127.0.0.1"), port=int(ccfg.get("port", 8000)), reload=False)
            return 0
        except ImportError as exc:
            print(f"Command center dependencies are missing: {exc}. Run: pip install -r requirements.txt")
            return 1
    config = Path(args.config)
    if not config.is_absolute():
        config = ROOT / config
    if not config.exists():
        print(f"Config not found: {config}")
        return 1


    # Late import so discovery/listing does not require pipeline dependencies.
    from pipeline.orchestrator import Pipeline

    if args.list_groups:
        pipeline = Pipeline(str(config), dataset_id=args.dataset_id)
        print("Configured dataset groups:")
        for group in pipeline._load_dataset_groups():
            print(f"  {group.get('id'):<32} {group.get('name', '')}")
        return 0

    pipeline = Pipeline(str(config), dataset_id=args.dataset_id)
    if args.no_resume:
        pipeline._resume = False

    stages = args.stages.strip().lower()
    try:
        if stages != "all":
            requested = [s.strip() for s in stages.split(",") if s.strip()]
            unknown = [s for s in requested if s not in STAGES]
            if unknown:
                print(f"Unknown stages: {unknown}. Valid: {STAGES}")
                return 1
            for stage in requested:
                pipeline.run(stage, dataset_group=args.dataset_group)
        else:
            pipeline.run("all", dataset_group=args.dataset_group)
    except KeyboardInterrupt:
        print("\nInterrupted. Atomic artifacts remain intact; rerun with resume enabled.")
        return 130
    except Exception as exc:
        print(f"\nPIPELINE FAILED: {type(exc).__name__}: {exc}")
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())






