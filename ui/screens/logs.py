import tkinter as tk
from . import *
class LogsScreen(tk.Frame):
 def __init__(self,parent):
  super().__init__(parent,bg=BG);self.root=frame(self,"Logs","Selected dataset event history and command-center activity. Secrets are not written to this view.");self.root.pack(fill="both",expand=True);button(self.root,"↻ Refresh",self.refresh).pack(anchor="w",pady=(0,10));self.box=card(self.root,"Event stream");self.box.pack(fill="both",expand=True);self.refresh()
 def refresh(self):
  for w in self.box.winfo_children():w.destroy()
  did=selected_id()
  if not did:return tk.Label(self.box,text="Select a dataset first.",bg=PANEL,fg=MUTED).pack(pady=40)
  try:d=registry.dataset().get(did);events=d.get("events",[])
  except Exception as e:events=[{"event":"error","data":{"message":str(e)}}]
  wrap,t=output(self.box);wrap.pack(fill="both",expand=True,padx=12,pady=12);show(t,"\n".join(f"[{x.get('ts','')}] {x.get('event','')} {x.get('data',{})}" for x in events[-250:]))
