import tkinter as tk
from ..core.config import PANEL,TEXT,MUTED
class MetricsPanel(tk.Frame):
 def __init__(self,parent,metrics=None):
  super().__init__(parent,bg=PANEL); self.labels={}
  for k,v in (metrics or {}).items(): self.add(k,v)
 def add(self,key,value):
  row=tk.Frame(self,bg=PANEL); row.pack(fill="x",padx=10,pady=3); tk.Label(row,text=str(key),bg=PANEL,fg=MUTED).pack(side="left"); l=tk.Label(row,text=str(value),bg=PANEL,fg=TEXT,font=("Consolas",10)); l.pack(side="right"); self.labels[key]=l
 def update(self,metrics):
  for k,v in metrics.items():
   if k in self.labels:self.labels[k].config(text=str(v))
   else:self.add(k,v)
