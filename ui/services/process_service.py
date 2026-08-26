"""Dependency-free localhost HTTP client."""
from __future__ import annotations
import json,urllib.request,urllib.error,urllib.parse
from ..core.config import CC_BASE_URL
class ProcessService:
    def request(self,path,method="GET",body=None,timeout=10):
        url=CC_BASE_URL+path
        data=json.dumps(body).encode() if body is not None else None
        req=urllib.request.Request(url,data=data,method=method,headers={"Content-Type":"application/json"} if data else {})
        try:
            with urllib.request.urlopen(req,timeout=timeout) as r: return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            detail=e.read().decode(errors="replace"); raise RuntimeError(f"HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e: raise ConnectionError(f"Command Center unavailable: {e.reason}") from e
    def get(self,path,timeout=10): return self.request(path,timeout=timeout)
    def post(self,path,body=None,timeout=30): return self.request(path,"POST",body,timeout)
    def delete(self,path,timeout=10): return self.request(path,"DELETE",timeout=timeout)
    def reachable(self):
        try:self.get("/api/system",3); return True
        except Exception:return False
