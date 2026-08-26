from __future__ import annotations
import json, os, re, shutil, hashlib
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from .config import DATASETS, ROOT, group_by_id, load_groups

LOCK = RLock()
SUBDIRS = ["raw","cleaned","dedup","weighted","tokenized","shards","checkpoints","model","agent","logs","metrics","errors"]
STAGES = ["crawl","clean","dedup","weight","tokenize","shard","train","export","model","agent"]


def now(): return datetime.now(timezone.utc).isoformat()

def atomic_json(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)

def safe_name(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._ -]+", "", s).strip().replace(" ", "-")
    return s[:80] or "dataset"

class DatasetStore:
    def __init__(self):
        DATASETS.mkdir(parents=True, exist_ok=True)

    def _ids(self):
        out=[]
        for p in DATASETS.glob("dataset_*"):
            if p.is_dir() and p.name[8:].isdigit(): out.append(int(p.name[8:]))
        return sorted(out)

    def next_id(self):
        ids=self._ids(); return (ids[-1]+1) if ids else 1
    def path(self, dataset_id: int): return DATASETS / f"dataset_{dataset_id:03d}"

    def create(self, name: str, description: str = "", group_id: str | None = None, group_config: dict | None = None):
        with LOCK:
            did=self.next_id(); root=self.path(did); root.mkdir(parents=True)
            for s in SUBDIRS: (root/s).mkdir()
            if group_id:
                group = group_by_id(group_id)
                if not group: raise ValueError(f"Unknown dataset group: {group_id}")
                group_config = None
            else:
                group = None
                group_config = group_config or {
                    "id": f"custom_{did:03d}", "name": name.strip() or f"Dataset {did}",
                    "sources": {"web": False, "github": False, "arxiv": False, "huggingface": False, "google": False}
                }
                group_id = group_config["id"]
            meta={
                "id": did, "dataset_id": f"dataset_{did:03d}", "name": name.strip() or f"Dataset {did}",
                "description": description, "group_id": group_id, "group_config": group_config,
                "created_at": now(), "updated_at": now(), "status": "NOT_STARTED",
                "stages": {s:"pending" for s in STAGES},
                "stats": {"files":0,"bytes":0,"documents":0,"words":0,"tokens":0},
                "model": None, "agent": {"status":"NOT_CREATED"}
            }
            atomic_json(root/"dataset.json", meta)
            atomic_json(root/"training.json", {"status":"NOT_STARTED","history":[]})
            (root/"manifest.jsonl").touch(); (root/"events.jsonl").touch()
            atomic_json(root/"dataset_config.json", {"group_id": group_id, "group_config": group_config})
            self.event(did,"dataset.created",{"name":meta["name"],"group_id":group_id})
            return meta

    def ensure_seed_datasets(self):
        groups = load_groups()
        existing = {d.get("group_id") for d in self.list()}
        for g in groups:
            if g.get("id") not in existing:
                self.create(g.get("name", g.get("id", "Dataset")), "Seeded from config/dataset_groups.yaml", group_id=g["id"])

        # If the hardened crawler was already used before the command center was
        # installed, preserve its per-group crawl artifacts instead of pretending
        # the new dashboard has never heard of them. Copy only the group crawl file
        # and its integrity manifest. Nothing is deleted or moved.
        for d in self.list():
            gid=d.get("group_id")
            if not gid: continue
            legacy=ROOT / "scratch" / f"01_crawled__{gid}.jsonl"
            target=self.path(d["id"]) / "scratch" / "01_crawled.jsonl"
            if legacy.exists() and not target.exists():
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(legacy,target)
                legacy_manifest=legacy.with_name(legacy.name + ".manifest.json")
                if legacy_manifest.exists():
                    shutil.copy2(legacy_manifest,target.with_name(target.name + ".manifest.json"))
                self.event(d["id"],"legacy_crawl.migrated",{"source":str(legacy),"destination":str(target)})
        return self.list()

    def get(self, did: int):
        p=self.path(did)/"dataset.json"
        if not p.exists(): return None
        return json.loads(p.read_text(encoding="utf-8"))

    def update(self, did: int, **changes):
        with LOCK:
            d=self.get(did)
            if not d: raise KeyError(did)
            d.update(changes); d["updated_at"]=now(); atomic_json(self.path(did)/"dataset.json",d); return d

    def list(self): return [self.get(i) for i in self._ids()]

    def event(self,did,event,data=None):
        p=self.path(did)/"events.jsonl"; p.parent.mkdir(parents=True,exist_ok=True)
        with p.open("a",encoding="utf-8") as f: f.write(json.dumps({"ts":now(),"event":event,"data":data or {}},ensure_ascii=False)+"\n")

    def manifest(self,did,record):
        with (self.path(did)/"manifest.jsonl").open("a",encoding="utf-8") as f: f.write(json.dumps(record,ensure_ascii=False)+"\n")

    def refresh_stats(self,did):
        root=self.path(did); files=0; total=0; words=0; documents=0
        # The real crawler writes JSONL into scratch, not raw/. Count the crawler
        # artifact first so the command center reports what was actually collected.
        candidates = []
        scratch = root / "scratch"
        if scratch.exists():
            candidates = sorted(scratch.glob("01_crawled*.jsonl"))
        if candidates:
            for fp in candidates:
                if not fp.exists(): continue
                total += fp.stat().st_size; files += 1
                try:
                    with fp.open(encoding="utf-8",errors="ignore") as f:
                        for line in f:
                            if line.strip():
                                documents += 1
                except OSError: pass
        else:
            raw=root/"raw"
            for p in raw.rglob("*"):
                if p.is_file(): files += 1; total += p.stat().st_size
            mp = root/"manifest.jsonl"
            if mp.exists(): documents=sum(1 for line in mp.open(encoding="utf-8",errors="ignore") if line.strip())

        # Prefer the latest processed corpus for word count when available.
        for corpus in [root/"scratch"/"04_weighted.jsonl", root/"scratch"/"03_deduped.jsonl", root/"scratch"/"02_cleaned.jsonl"]:
            if corpus.exists():
                try:
                    for line in corpus.open(encoding="utf-8",errors="ignore"):
                        if line.strip():
                            try:
                                obj=json.loads(line); words += len(str(obj.get("text", "")).split())
                            except Exception: pass
                except OSError: pass
                break
        d=self.get(did)
        d["stats"]={**d.get("stats",{}),"files":files,"bytes":total,"documents":documents,"words":words}
        d["updated_at"]=now(); atomic_json(root/"dataset.json",d); return d["stats"]

    def ingest_path(self,did,source: Path):
        root=self.path(did); dest=root/"raw"; source=source.resolve()
        if not source.exists(): raise FileNotFoundError(source)
        paths=[source] if source.is_file() else [p for p in source.rglob("*") if p.is_file()]
        count=0
        for p in paths:
            try:
                rel=p.name if source.is_file() else p.relative_to(source).as_posix()
                target=dest/rel; target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,target)
                h=hashlib.sha256(target.read_bytes()).hexdigest()
                self.manifest(did,{"path":str(target.relative_to(root)),"source":str(p),"sha256":h,"size":target.stat().st_size,"collected_at":now()}); count+=1
            except Exception as e:
                with (root/"errors"/"ingest_errors.jsonl").open("a",encoding="utf-8") as f: f.write(json.dumps({"source":str(p),"error":str(e),"ts":now()})+"\n")
        self.refresh_stats(did); self.event(did,"ingest.completed",{"files":count});
        stages={**self.get(did)["stages"],"crawl":"complete"}; self.update(did,status="COLLECTED",stages=stages); return self.get(did)

    def refresh_pipeline_state(self,did):
        root=self.path(did); d=self.get(did)
        if not d: return None
        self.refresh_stats(did); d=self.get(did)
        checks={
            "crawl": list((root/"scratch").glob("01_crawled*.jsonl")) if (root/"scratch").exists() else [],
            "clean": [root/"scratch"/"02_cleaned.jsonl"],
            "dedup": [root/"scratch"/"03_deduped.jsonl"],
            "weight": [root/"scratch"/"04_weighted.jsonl"],
            "tokenize": [root/"tokenizer"/"tokenizer.json"],
            "shard": list((root/"shards").glob("shard_*.bin")),
            "train": list((root/"checkpoints").glob("ckpt_final_*.pt")),
            "export": [root/"gguf"/"Modelfile"],
        }
        for stage, paths in checks.items():
            if paths and all(p.exists() and (p.stat().st_size > 0) for p in paths): d["stages"][stage]="complete"
        if d["stages"].get("export")=="complete": d["status"]="COMPLETE"
        elif d["stages"].get("train")=="complete": d["status"]="TRAINED"
        elif any(v=="running" for v in d["stages"].values()): d["status"]="RUNNING"
        elif d["stats"].get("documents",0): d["status"]="COLLECTED"
        atomic_json(root/"dataset.json",d); return d

    def tail_events(self,did,limit=100):
        p=self.path(did)/"events.jsonl"
        if not p.exists(): return []
        lines=p.read_text(encoding="utf-8",errors="ignore").splitlines()[-limit:]
        return [json.loads(x) for x in lines if x.strip()]

store = DatasetStore()
