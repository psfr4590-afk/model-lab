import tkinter as tk
from tkinter import ttk
from ..core.config import PANEL,MUTED
class ProgressPanel(tk.Frame):
 def __init__(self,parent,label="Progress"):
  super().__init__(parent,bg=PANEL); tk.Label(self,text=label,bg=PANEL,fg=MUTED).pack(anchor="w",padx=10,pady=(7,3)); self.bar=ttk.Progressbar(self,mode="determinate",maximum=100); self.bar.pack(fill="x",padx=10,pady=(0,8))
 def set(self,value): self.bar["value"]=value
