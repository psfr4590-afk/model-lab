from . import *
import tkinter as tk
from tkinter import messagebox
class TrainingScreen(tk.Frame):
 def __init__(self,parent):
  super().__init__(parent,bg=BG); self.root=frame(self,"Training","Training status and controlled train/stop operations."); self.root.pack(fill="both",expand=True); bar=toolbar(self.root); bar.pack(fill="x",pady=(0,10)); button(bar,"↻ Refresh",self.refresh).pack(side="left"); button(bar,"▶ Start Training",self.start,"primary").pack(side="left",padx=7); button(bar,"Stop",self.stop,"danger").pack(side="left"); self.metrics=tk.Frame(self.root,bg=BG); self.metrics.pack(fill="x",pady=(0,12)); self.box=card(self.root,"Training control"); self.box.pack(fill="both",expand=True); self.refresh()
 def refresh(self):
  for w in self.metrics.winfo_children(): w.destroy()
  for w in self.box.winfo_children(): w.destroy()
  did=selected_id()
  if not did: tk.Label(self.box,text="No dataset selected.",bg=PANEL,fg=MUTED,font=("Segoe UI",11)).pack(pady=40); return
  try: d=registry.training().state(did); d=d if isinstance(d,dict) else {}
  except Exception as e: d={"error":str(e)}
  vals=[("Status",d.get("status","idle"),SUCCESS if d.get("status")=="running" else TEXT),("Device",d.get("device","—"),TEXT),("Model",d.get("model",d.get("model_type","85M target")),TEXT),("Parameters",f"{int(d.get('parameters',0)):,}",TEXT)]
  for x in vals: metric(self.metrics,*x).pack(side="left",fill="x",expand=True,padx=(0,10))
  tk.Label(self.box,text="Training remains an explicit pipeline stage. Opening this screen never starts training.",bg=PANEL,fg=MUTED,font=("Segoe UI",10)).pack(anchor="w",padx=14,pady=16)
 def start(self):
  did=selected_id()
  if did and messagebox.askyesno("Training","Start the train stage for the selected dataset?",parent=self):
   try: registry.training().start(did); self.refresh()
   except Exception as e: messagebox.showerror("Training",str(e))
 def stop(self):
  did=selected_id()
  if did:
   try: registry.training().stop(did); self.refresh()
   except Exception as e: messagebox.showerror("Training",str(e))
