from __future__ import annotations
import os, subprocess, threading, traceback, sys
from .config import ROOT
from .store import DatasetStore
from .secrets import credentials

store=DatasetStore(); RUNS={}; RUN_LOCK=threading.RLock()

STAGE_MAP={"crawl":"crawl","clean":"clean","dedup":"dedup","weight":"weight","tokenize":"tokenize","shard":"shard","train":"train","export":"export"}

def _log(did,msg):
    p=store.path(did)/"logs"/"command-center.log"; p.parent.mkdir(exist_ok=True)
    with p.open("a",encoding="utf-8") as f: f.write(msg+"\n")
    store.event(did,"log",{"message":msg})

def _run(did,stage):
    root=store.path(did); d=store.get(did)
    stages=dict(d["stages"]); stages[stage]="running"; store.update(did,stages=stages,status="RUNNING")
    env=os.environ.copy(); env.update({"DATASET_ID":str(did),"DATASET_DIR":str(root),"PROJECT_ROOT":str(ROOT)})
    # Inject only credentials explicitly mapped to environment variables.
    # Secrets never enter command-center logs or dataset metadata.
    try:
        env.update(credentials.environment())
    except Exception as exc:
        _log(did, f"[credentials] unavailable: {exc}")
    cmd=[sys.executable,str(ROOT/"run_pipeline.py"),"--dataset-id",str(did),"--stages",STAGE_MAP[stage]]
    _log(did,"[{}] START {}".format(stage," ".join(cmd)))
    try:
        proc=subprocess.Popen(cmd,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
        with RUN_LOCK: RUNS[did]=proc
        for line in proc.stdout:
            _log(did,f"[{stage}] {line.rstrip()}")
        code=proc.wait(); stages=dict(store.get(did)["stages"]); stages[stage]="complete" if code==0 else "failed"
        store.update(did,stages=stages,status="ERROR" if code else ("TRAINED" if stage=="train" else "RUNNING"))
        _log(did,f"[{stage}] EXIT {code}")
    except Exception:
        stages=dict(store.get(did)["stages"]); stages[stage]="failed"; store.update(did,stages=stages,status="ERROR"); _log(did,traceback.format_exc())
    finally:
        with RUN_LOCK: RUNS.pop(did,None)
        store.refresh_pipeline_state(did)

def stop(did):
    with RUN_LOCK: p=RUNS.get(did)
    if p and p.poll() is None:
        p.terminate(); return True
    return False

def start_stage(did,stage):
    if not store.get(did): raise ValueError(f"Unknown dataset {did}")
    t=threading.Thread(target=_run,args=(did,stage),daemon=True); t.start(); return {"started":True,"dataset_id":did,"stage":stage}
