from __future__ import annotations
from pathlib import Path
from .store import store
from .runner import start_stage, stop
from .config import load_groups
from .secrets import credentials

def init(): return store.ensure_seed_datasets()
def add(name,description="",group_id=None): return store.create(name,description,group_id=group_id)
def ingest(did,path): return store.ingest_path(did,Path(path))
def stage(did,name):
    if name not in {"crawl","clean","dedup","weight","tokenize","shard","train","export"}: raise ValueError(name)
    return start_stage(did,name)
def status(did=None):
    if did:
        return store.refresh_pipeline_state(did)
    return [store.refresh_pipeline_state(d["id"]) for d in store.list()]
def groups(): return load_groups()


def credential_list(): return credentials.list()
def credential_set(name, secret, provider="custom", kind="token", env_var="", description="", identity=""): return credentials.set(name, secret, provider, kind, env_var, description, identity)
def credential_delete(name): return credentials.delete(name)
def credential_test(name): return credentials.test(name)
