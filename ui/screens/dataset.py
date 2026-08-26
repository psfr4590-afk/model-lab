from . import *
import tkinter as tk
from tkinter import messagebox,simpledialog,filedialog
from ..core import navigation
class DatasetScreen(tk.Frame):
 def __init__(self,parent):
  super().__init__(parent,bg=BG); self.root=frame(self,"Datasets","Independent dataset sessions. Dataset 001–004 are seeded from dataset_groups.yaml; additional sessions may be created."); self.root.pack(fill="both",expand=True); bar=toolbar(self.root);bar.pack(fill="x",pady=(0,10));button(bar,"↻ Refresh",self.refresh).pack(side="left");button(bar,"＋ Create",self.create,"primary").pack(side="left",padx=7);button(bar,"Ingest Files",self.ingest).pack(side="left");self.box=card(self.root,"Dataset sessions");self.box.pack(fill="both",expand=True);self.refresh()
 def refresh(self):
  for w in self.box.winfo_children():w.destroy()
  try:ds=registry.dataset().list();state.set("datasets",ds)
  except Exception as e:ds=[];tk.Label(self.box,text=f"Backend error: {e}",bg=PANEL,fg=ERROR).pack(padx=14,pady=14)
  grid=tk.Frame(self.box,bg=PANEL);grid.pack(fill="both",expand=True,padx=12,pady=12)
  for c in range(3):grid.columnconfigure(c,weight=1)
  for i,d in enumerate(ds):self.card_item(grid,d,i//3,i%3)
 def card_item(self,parent,d,r,c):
  active=d.get("id")==selected_id();bg=ACTIVE if active else PANEL2;f=tk.Frame(parent,bg=bg,highlightbackground=ACCENT if active else LINE,highlightthickness=1,cursor="hand2");f.grid(row=r,column=c,sticky="nsew",padx=5,pady=5)
  tk.Label(f,text=f"DATASET {int(d['id']):03d}",bg=bg,fg=ACCENT,font=("Consolas",8,"bold")).pack(anchor="w",padx=12,pady=(11,2));tk.Label(f,text=d.get("name","Dataset"),bg=bg,fg=TEXT,font=("Segoe UI",10,"bold"),wraplength=300,justify="left").pack(anchor="w",padx=12);tk.Label(f,text=f"{d.get('status','NOT_STARTED')} · {d.get('stats',{}).get('documents',0):,} docs",bg=bg,fg=MUTED,font=("Consolas",8)).pack(anchor="w",padx=12,pady=5);tk.Label(f,text=d.get("group_id","custom"),bg=bg,fg=MUTED,font=("Segoe UI",8),wraplength=300).pack(anchor="w",padx=12,pady=(0,10))
  for w in [f,*f.winfo_children()]:w.bind("<Button-1>",lambda e,did=d["id"]:self.select(did))
 def select(self,did):state.set("selected_dataset_id",did);navigation.navigate("Pipeline")
 def create(self):
  name=simpledialog.askstring("Create Dataset","Dataset name:",parent=self)
  if not name:return
  try:d=registry.dataset().create(name);state.set("selected_dataset_id",d["id"]);self.refresh()
  except Exception as e:messagebox.showerror("Dataset",str(e),parent=self)
 def ingest(self):
  did=selected_id();path=filedialog.askdirectory(parent=self)
  if not did:return messagebox.showinfo("Ingest","Select a dataset first.",parent=self)
  if path:
   try:registry.dataset().ingest(did,path);self.refresh()
   except Exception as e:messagebox.showerror("Ingest",str(e),parent=self)
