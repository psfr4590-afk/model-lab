from . import *
import tkinter as tk
from tkinter import messagebox,simpledialog
class PipelineScreen(tk.Frame):
 def __init__(self,parent):
  super().__init__(parent,bg=BG); self.root=frame(self,"Pipeline","Stage-by-stage execution through the Command Center."); self.root.pack(fill="both",expand=True); bar=toolbar(self.root); bar.pack(fill="x",pady=(0,10)); button(bar,"↻ Refresh State",self.refresh).pack(side="left"); button(bar,"▶ Run Selected Stage",self.run,"primary").pack(side="left",padx=7); button(bar,"Stop",self.stop,"danger").pack(side="left"); self.box=card(self.root,"Pipeline stages"); self.box.pack(fill="both",expand=True); self.refresh()
 def refresh(self):
  for w in self.box.winfo_children(): w.destroy()
  did=selected_id()
  if not did: tk.Label(self.box,text="No dataset selected. Use Dataset → Select ID.",bg=PANEL,fg=MUTED,font=("Segoe UI",11)).pack(pady=40); return
  try: d=registry.pipeline().state(did)
  except Exception as e: tk.Label(self.box,text=f"Pipeline API error: {e}",bg=PANEL,fg=ERROR).pack(padx=14,pady=14); return
  stages=d.get("stages",{}) if isinstance(d,dict) else {}
  grid=tk.Frame(self.box,bg=PANEL); grid.pack(fill="both",expand=True,padx=12,pady=12)
  for i,s in enumerate(STAGES):
   r,c=divmod(i,4); st=stages.get(s,"idle"); f=tk.Frame(grid,bg=PANEL2,highlightbackground=LINE,highlightthickness=1); f.grid(row=r,column=c,sticky="nsew",padx=4,pady=4); grid.columnconfigure(c,weight=1); tk.Label(f,text=s.upper(),bg=PANEL2,fg=TEXT,font=("Segoe UI",10,"bold")).pack(anchor="w",padx=12,pady=(12,3)); tk.Label(f,text=st,bg=PANEL2,fg=SUCCESS if st=="complete" else ACCENT if st=="running" else WARNING if st=="failed" else MUTED,font=("Consolas",9)).pack(anchor="w",padx=12,pady=(0,10)); button(f,"Run",lambda stage=s:self.run_stage(stage),"primary").pack(anchor="w",padx=10,pady=(0,10))
  for c in range(4): grid.columnconfigure(c,weight=1)
 def run_stage(self,stage):
  did=selected_id()
  if did:
   try: registry.pipeline().run_stage(did,stage); self.refresh()
   except Exception as e: messagebox.showerror("Pipeline",str(e))
 def run(self):
  stage=simpledialog.askstring("Stage","Stage name:",parent=self)
  if stage: self.run_stage(stage)
 def stop(self):
  did=selected_id()
  if did:
   try: registry.pipeline().stop(did); self.refresh()
   except Exception as e: messagebox.showerror("Pipeline",str(e))
