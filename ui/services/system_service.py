"""System and GPU inspection."""
import platform,shutil,subprocess,sys,os
from ..core import registry
class SystemService:
 def info(self):
  try:return registry.process().get("/api/system")
  except Exception: return {"platform":platform.platform(),"python":platform.python_version(),"python_executable":sys.executable,"cpu":os.cpu_count(),"git":shutil.which("git") or "NOT FOUND","cmake":shutil.which("cmake") or "NOT FOUND","gpu":"UNAVAILABLE","cuda_available":False,"_source":"local"}
 def gpu(self):
  out=[]
  try:
   p=subprocess.run(["nvidia-smi","--query-gpu=name,driver_version,memory.total,memory.used,memory.free","--format=csv"],capture_output=True,text=True,timeout=10,check=False); out.append(p.stdout or p.stderr)
  except Exception as e:out.append(f"nvidia-smi: {e}")
  return "\n".join(x.strip() for x in out if x.strip()) or "GPU information unavailable."
