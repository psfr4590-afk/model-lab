from pathlib import Path
from ..core.config import ROOT
class OutputService:
 def inventory(self):
  roots=[ROOT/"datasets",ROOT/"models",ROOT/"output"]
  out=[]
  for r in roots:
   if r.exists():
    files=[p for p in r.rglob("*") if p.is_file()]; out.append((str(r.relative_to(ROOT)),len(files),sum(p.stat().st_size for p in files)))
  return out
 def dataset_tree(self,did):
  r=ROOT/"datasets"/f"dataset_{int(did):03d}"; return [str(p.relative_to(r)) for p in r.rglob("*") if p.is_file()] if r.exists() else []
