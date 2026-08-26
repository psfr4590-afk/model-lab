from . import *
import tkinter as tk
class OutputsScreen(tk.Frame):
 def __init__(self,parent):
  super().__init__(parent,bg=BG); self.root=frame(self,"Outputs","Models, checkpoints, shards and generated artifacts."); self.root.pack(fill="both",expand=True); button(self.root,"↻ Refresh",self.refresh).pack(anchor="w",pady=(0,10)); self.box=card(self.root,"Output inventory"); self.box.pack(fill="both",expand=True); self.refresh()
 def refresh(self):
  for w in self.box.winfo_children(): w.destroy()
  try: rows=registry.output().inventory()
  except Exception: rows=[]
  if not rows: tk.Label(self.box,text="No output roots found.",bg=PANEL,fg=MUTED).pack(pady=40); return
  for p,n,s in rows:
   row=tk.Frame(self.box,bg=PANEL2,highlightbackground=LINE,highlightthickness=1); row.pack(fill="x",padx=12,pady=4); tk.Label(row,text=str(p),bg=PANEL2,fg=TEXT,anchor="w").pack(side="left",fill="x",expand=True,padx=10,pady=9); tk.Label(row,text=f"{n} files · {s/1024**2:.2f} MB",bg=PANEL2,fg=MUTED).pack(side="right",padx=10)
