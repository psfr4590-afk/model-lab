from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from .service import add, ingest, stage, status, init, groups, credential_list, credential_set, credential_delete, credential_test
from .store import store
from .runner import stop

@asynccontextmanager
async def lifespan(app):
    init()
    yield

app=FastAPI(title="Model Lab · M²S Model Training Pipeline",version="1.0.0",docs_url="/api/docs", lifespan=lifespan)
templates=Jinja2Templates(directory=str(__import__('pathlib').Path(__file__).parent/'templates'))

class DatasetCreate(BaseModel): name:str; description:str=""; group_id:str|None=None
class IngestRequest(BaseModel): path:str
class CredentialSet(BaseModel):
    name:str
    secret:str
    provider:str="custom"
    kind:str="token"
    env_var:str=""
    description:str=""
    identity:str=""

@app.get("/",response_class=HTMLResponse)
def index(request:Request):
    # Jinja2Templates.TemplateResponse expects the template name first and a context dict
    # that includes the request under the "request" key.
    return templates.TemplateResponse("index.html", {"request": request})
@app.get("/api/groups")
def group_list(): return groups()
@app.get("/api/datasets")
def datasets(): return status()
@app.post("/api/datasets")
def create(x:DatasetCreate):
    try:return add(x.name,x.description,x.group_id)
    except Exception as e: raise HTTPException(400,str(e)) from e
@app.get("/api/datasets/{did}")
def dataset(did:int):
    d=status(did)
    if not d: raise HTTPException(404,"Dataset not found")
    d["events"]=store.tail_events(did,150); return d
@app.post("/api/datasets/{did}/ingest")
def ingest_api(did:int,x:IngestRequest):
    try:return ingest(did,x.path)
    except FileNotFoundError as e: raise HTTPException(404,str(e)) from e
@app.post("/api/datasets/{did}/stage/{name}")
def run_stage(did:int,name:str):
    try:return stage(did,name)
    except Exception as e: raise HTTPException(400,str(e)) from e
@app.post("/api/datasets/{did}/stop")
def stop_stage(did:int): return {"stopped":stop(did)}



@app.get("/api/system")
def system_api():
    import os, platform, shutil, subprocess, sys
    out={"platform":platform.platform(),"python":sys.version.split()[0],"python_executable":sys.executable,"cpu":os.cpu_count(),"git":shutil.which("git") or "NOT FOUND","cmake":shutil.which("cmake") or "NOT FOUND"}
    try:
        r=subprocess.run(["nvidia-smi","--query-gpu=name,driver_version,memory.total,memory.free","--format=csv,noheader"],capture_output=True,text=True,timeout=5,check=False)
        out["gpu"]=r.stdout.strip() if r.returncode==0 else "UNAVAILABLE"
    except Exception:
        out["gpu"]="UNAVAILABLE"
    try:
        import torch
        out["torch"]=torch.__version__; out["cuda_available"]=bool(torch.cuda.is_available()); out["cuda_runtime"]=torch.version.cuda
        if torch.cuda.is_available(): out["torch_gpu"]=torch.cuda.get_device_name(0)
    except Exception as e:
        out["torch"]=f"ERROR: {type(e).__name__}"; out["cuda_available"]=False
    return out

@app.get("/api/credentials")
def credentials_api():
    return credential_list()

@app.post("/api/credentials")
def credentials_set_api(x:CredentialSet):
    try: return credential_set(x.name, x.secret, x.provider, x.kind, x.env_var, x.description, x.identity)
    except Exception as e: raise HTTPException(400, str(e)) from e

@app.post("/api/credentials/{name}/test")
def credentials_test_api(name:str):
    try: return credential_test(name)
    except KeyError: raise HTTPException(404, "Credential not found") from None
    except Exception as e: raise HTTPException(400, str(e)) from e

@app.delete("/api/credentials/{name}")
def credentials_delete_api(name:str):
    return {"deleted": credential_delete(name)}
