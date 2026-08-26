from . import *
import tkinter as tk
class SourcesScreen(tk.Frame):
 def __init__(self,parent):
  super().__init__(parent,bg=BG); self.root=frame(self,"Sources","Configured dataset groups and crawl source definitions."); self.root.pack(fill="both",expand=True); button(self.root,"↻ Refresh",self.refresh).pack(anchor="w",pady=(0,10)); self.box=card(self.root,"Configured sources"); self.box.pack(fill="both",expand=True); self.refresh()
 def refresh(self):
  for w in self.box.winfo_children(): w.destroy()
  try: data=registry.dataset().groups()
  except Exception as e: data=f"Source configuration unavailable: {e}"
  tk.Label(self.box,text=repr(data),bg=PANEL,fg=TEXT,font=("Consolas",9),anchor="nw",justify="left").pack(fill="both",expand=True,padx=14,pady=12)
