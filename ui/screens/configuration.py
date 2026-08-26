import tkinter as tk
from . import *
from ..core.config import ROOT
class ConfigurationScreen(tk.Frame):
 def __init__(self,parent):
  super().__init__(parent,bg=BG);self.root=frame(self,"Configuration","Existing configuration sources used by the pipeline. This screen does not create a second configuration system.");self.root.pack(fill="both",expand=True);self.box=card(self.root,"Configuration files");self.box.pack(fill="both",expand=True);self.refresh()
 def refresh(self):
  for w in self.box.winfo_children():w.destroy()
  paths=["config/pipeline_config.yaml","config/dataset_groups.yaml","config/cleaner_config.yaml","config/source_weights.yaml","config/seed_urls.txt","config/credentials.example.yaml","config/.env.example"]
  for rel in paths:
   p=ROOT/rel;row=tk.Frame(self.box,bg=PANEL2,highlightbackground=LINE,highlightthickness=1);row.pack(fill="x",padx=12,pady=4);tk.Label(row,text="PRESENT" if p.exists() else "MISSING",bg=PANEL2,fg=SUCCESS if p.exists() else ERROR,font=("Consolas",8,"bold"),width=9,anchor="w").pack(side="left",padx=10,pady=9);tk.Label(row,text=rel,bg=PANEL2,fg=TEXT,font=("Consolas",9),anchor="w").pack(side="left",fill="x",expand=True)
