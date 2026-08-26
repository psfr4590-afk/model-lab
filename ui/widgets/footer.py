import tkinter as tk
from ..core.config import PANEL,MUTED
class Footer(tk.Frame):
 def __init__(self,parent,text="Local • M²S Model Training Pipeline"):
  super().__init__(parent,bg=PANEL); tk.Label(self,text=text,bg=PANEL,fg=MUTED,font=("Consolas",8)).pack(anchor="w",padx=10,pady=4)
