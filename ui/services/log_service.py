from pathlib import Path
from ..core.config import ROOT
class LogService:
 def files(self):
  roots=[ROOT/"datasets",ROOT/".runtime"]
  out=[]
  for r in roots:
   if r.exists(): out += [p for p in r.rglob("*") if p.is_file() and "log" in p.name.lower()]
  return out
 def tail(self,path,lines=80):
  p=Path(path)
  if not p.exists(): return ""
  return "".join(p.read_text(encoding="utf-8",errors="replace").splitlines(True)[-lines:])
