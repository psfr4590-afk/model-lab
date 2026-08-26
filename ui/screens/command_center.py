from . import *
import tkinter as tk
class CommandCenterScreen(tk.Frame):
 def __init__(self,parent):
  super().__init__(parent,bg=BG); self.root=frame(self,"Command Center","FastAPI service health and API state."); self.root.pack(fill="both",expand=True); button(self.root,"↻ Refresh",self.refresh).pack(anchor="w",pady=(0,10)); self.box=card(self.root,"API state"); self.box.pack(fill="both",expand=True); self.refresh()
 def refresh(self):
  for w in self.box.winfo_children(): w.destroy()
  try: data=registry.process().get("/api/system")
  except Exception as e: data=f"Command Center unavailable: {e}"
  tk.Label(self.box,text=repr(data),bg=PANEL,fg=TEXT,font=("Consolas",9),anchor="nw",justify="left").pack(fill="both",expand=True,padx=14,pady=12)
