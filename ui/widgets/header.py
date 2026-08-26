import tkinter as tk
from ..core.config import PANEL,TEXT,MUTED,ACCENT
class Header(tk.Frame):
 def __init__(self,parent,title,subtitle=""):
  super().__init__(parent,bg=PANEL); tk.Label(self,text=title,bg=PANEL,fg=ACCENT,font=("Segoe UI",16,"bold")).pack(anchor="w",padx=14,pady=(8,0)); tk.Label(self,text=subtitle,bg=PANEL,fg=MUTED,font=("Segoe UI",9)).pack(anchor="w",padx=15,pady=(0,8))
