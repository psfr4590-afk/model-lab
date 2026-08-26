from . import *
import tkinter as tk
class DashboardScreen(tk.Frame):
 def __init__(self,parent):
  super().__init__(parent,bg=BG); self.root=frame(self,"Dashboard","M²S Model Training Pipeline overview and operational state."); self.root.pack(fill="both",expand=True); self.build()
 def build(self):
  for w in self.root.winfo_children(): w.destroy()
  top=frame(self.root,"Dashboard","M²S Model Training Pipeline overview and operational state."); top.pack(fill="x")
  try: ds=registry.dataset().list(); state.set("datasets",ds); online=bool(state.get("api_reachable")); running=sum("run" in str(d.get("status","")).lower() for d in ds); docs=sum(int(d.get("stats",{}).get("documents",0)) for d in ds)
  except Exception: ds=[]; online=False; running=0; docs=0
  metrics=tk.Frame(self.root,bg=BG); metrics.pack(fill="x",pady=(0,12)); [metric(metrics,*x).pack(side="left",fill="x",expand=True,padx=(0,10)) for x in [("Dataset Sessions",len(ds),TEXT),("Running",running,WARNING if running else SUCCESS),("Documents",f"{docs:,}",TEXT),("API", "ONLINE" if online else "OFFLINE",SUCCESS if online else ERROR)]]
  c=card(self.root,"System posture"); c.pack(fill="x",pady=(0,12));
  for a,b in [("Control surface","ONLINE"),("Execution mode","Explicit action required"),("Backend","FastAPI / existing pipeline"),("Credentials","Encrypted at rest; secrets never displayed")]:
   row=tk.Frame(c,bg=PANEL); row.pack(fill="x",padx=14,pady=3); tk.Label(row,text=a,bg=PANEL,fg=MUTED,width=24,anchor="w").pack(side="left"); tk.Label(row,text=b,bg=PANEL,fg=SUCCESS if a=="Control surface" else TEXT,anchor="w").pack(side="left")
  c2=card(self.root,"Pipeline"); c2.pack(fill="both",expand=True); grid=tk.Frame(c2,bg=PANEL); grid.pack(fill="both",expand=True,padx=12,pady=(0,12));
  for i,s in enumerate(STAGES):
   r,cx=divmod(i,4); st=(ds[0].get("stages",{}).get(s,"idle") if ds else "idle"); f=tk.Frame(grid,bg=PANEL2,highlightbackground=LINE,highlightthickness=1); f.grid(row=r,column=cx,sticky="nsew",padx=4,pady=4); grid.columnconfigure(cx,weight=1); tk.Label(f,text=s.upper(),bg=PANEL2,fg=TEXT,font=("Segoe UI",9,"bold")).pack(anchor="w",padx=10,pady=(9,3)); tk.Label(f,text=st,bg=PANEL2,fg=ACCENT if st=="running" else SUCCESS if st=="complete" else MUTED,font=("Consolas",8)).pack(anchor="w",padx=10,pady=(0,9))
