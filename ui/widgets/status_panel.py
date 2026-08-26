import tkinter as tk
from ..core.config import PANEL,TEXT,MUTED,SUCCESS,ERROR
class StatusPanel(tk.Frame):
 def __init__(self,parent,label,value="UNKNOWN"):
  super().__init__(parent,bg=PANEL); tk.Label(self,text=label,bg=PANEL,fg=MUTED,font=("Segoe UI",9)).pack(anchor="w",padx=10,pady=(7,0)); self.value=tk.Label(self,text=value,bg=PANEL,fg=TEXT,font=("Segoe UI",11,"bold")); self.value.pack(anchor="w",padx=10,pady=(0,7))
 def set(self,value): self.value.config(text=value)
def placeholder(parent,title):
 f=tk.Frame(parent,bg=PANEL); tk.Label(f,text=title,bg=PANEL,fg=TEXT,font=("Segoe UI",18,"bold")).pack(padx=30,pady=30); return f
