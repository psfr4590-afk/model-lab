import tkinter as tk
from ..core.config import CODE_BG,TEXT
class LogPanel(tk.Frame):
 def __init__(self,parent):
  super().__init__(parent,bg=CODE_BG); self.text=tk.Text(self,bg=CODE_BG,fg=TEXT,relief="flat",font=("Consolas",9),wrap="none"); self.text.pack(fill="both",expand=True)
 def set(self,text): self.text.delete("1.0","end"); self.text.insert("end",text)
