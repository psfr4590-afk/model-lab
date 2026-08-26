from . import *
import tkinter as tk
from tkinter import messagebox
PRESETS=[
("github","GitHub","API token","GITHUB_TOKEN","GitHub repository crawling."),
("huggingface","Hugging Face","Hub token","HF_TOKEN","Gated/private Hugging Face datasets."),
("google_api","Google","API key","GOOGLE_API_KEY","Google Programmable Search JSON API."),
("google_cx","Google","Search engine ID","GOOGLE_CX","Google Programmable Search engine identifier."),]
class CredentialsScreen(tk.Frame):
 def __init__(self,parent):
  super().__init__(parent,bg=BG); self.root=frame(self,"Credentials","Four credential slots are already defined. Enter only the required value. Stored secrets are encrypted and never displayed."); self.root.pack(fill="both",expand=True); self.box=card(self.root,"Credential registry"); self.box.pack(fill="both",expand=True); self.refresh()
 def refresh(self):
  for w in self.box.winfo_children():w.destroy()
  try: existing={x["name"]:x for x in registry.credentials().list()}
  except Exception as e: existing={}; tk.Label(self.box,text=f"Credential API error: {e}",bg=PANEL,fg=ERROR).pack(padx=14,pady=14)
  for name,provider,kind,env,desc in PRESETS:self.row(name,provider,kind,env,desc,existing.get(name))
 def row(self,name,provider,kind,env,desc,current):
  f=tk.Frame(self.box,bg=PANEL2,highlightbackground=LINE,highlightthickness=1); f.pack(fill="x",padx=12,pady=6)
  top=tk.Frame(f,bg=PANEL2); top.pack(fill="x",padx=12,pady=(10,2)); tk.Label(top,text=f"{provider} · {kind}",bg=PANEL2,fg=TEXT,font=("Segoe UI",10,"bold")).pack(side="left"); tk.Label(top,text="CONFIGURED" if current else "NOT SET",bg=PANEL2,fg=SUCCESS if current else WARNING,font=("Consolas",8,"bold")).pack(side="right")
  tk.Label(f,text=f"{env} · {desc}",bg=PANEL2,fg=MUTED,font=("Consolas",8)).pack(anchor="w",padx=12)
  e=tk.Entry(f,bg=CODE_BG,fg=TEXT,insertbackground=TEXT,show="•",relief="flat",font=("Consolas",9)); e.pack(side="left",fill="x",expand=True,padx=(12,8),pady=10,ipady=7)
  button(f,"Save / Replace",lambda:self.save(name,provider,kind,env,desc,e),"primary").pack(side="right",padx=(0,12),pady=10)
 def save(self,name,provider,kind,env,desc,e):
  secret=e.get()
  if not secret:return messagebox.showwarning("Credentials","Enter a value first.",parent=self)
  try:registry.credentials().set(name,secret,provider,kind,env,desc);e.delete(0,"end");self.refresh()
  except Exception as ex:messagebox.showerror("Credentials",str(ex),parent=self)
