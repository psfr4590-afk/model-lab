from . import *
import tkinter as tk
from pathlib import Path
class DiagnosticsScreen(tk.Frame):
 def __init__(self,parent):
  super().__init__(parent,bg=BG); self.root=frame(self,"Diagnostics","Read-only structural, dependency and runtime checks."); self.root.pack(fill="both",expand=True); button(self.root,"✓ Run Diagnostics",self.refresh,"primary").pack(anchor="w",pady=(0,10)); self.box=card(self.root,"Structural checks"); self.box.pack(fill="both",expand=True); self.refresh()
 def refresh(self):
  for w in self.box.winfo_children(): w.destroy()
  root=Path(__file__).resolve().parents[2]; checks=["README.md","PROJECT_STATE.md","launch.py","run_pipeline.py","run_command_center.py","ui","config","scripts","pipeline","command_center","command_center/web.py",".runtime/environment.json"]
  for x in checks:
   ok=(root/x).exists(); row=tk.Frame(self.box,bg=PANEL); row.pack(fill="x",padx=14,pady=3); tk.Label(row,text="PASS" if ok else "FAIL",bg=PANEL,fg=SUCCESS if ok else ERROR,font=("Consolas",8,"bold"),width=6,anchor="w").pack(side="left"); tk.Label(row,text=x,bg=PANEL,fg=TEXT).pack(side="left")
  tk.Label(self.box,text="llama.cpp is an optional external dependency; it is not required to be present in this repository.",bg=PANEL,fg=MUTED,font=("Segoe UI",9)).pack(anchor="w",padx=14,pady=14)
