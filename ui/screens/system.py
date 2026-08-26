from . import *
import tkinter as tk
class SystemScreen(tk.Frame):
 def __init__(self,parent): super().__init__(parent,bg=BG); self.root=frame(self,"System","Operating system, Python, GPU and build environment."); self.root.pack(fill="both",expand=True); button(self.root,"↻ Refresh",self.refresh).pack(anchor="w",pady=(0,10)); self.box=card(self.root,"Host environment"); self.box.pack(fill="both",expand=True); self.refresh()
 def refresh(self):
  for w in self.box.winfo_children(): w.destroy()
  try: d=registry.system().info(); gpu=registry.system().gpu()
  except Exception as e: d={"error":str(e)}; gpu="unavailable"
  for k,v in list(d.items())+[('GPU detail',gpu)]:
   row=tk.Frame(self.box,bg=PANEL); row.pack(fill="x",padx=14,pady=4); tk.Label(row,text=str(k),bg=PANEL,fg=MUTED,width=24,anchor="w").pack(side="left"); tk.Label(row,text=str(v),bg=PANEL,fg=TEXT,anchor="w").pack(side="left",fill="x",expand=True)
