"""Shared visual primitives for the M\u00b2S Model Training Pipeline UI."""
import tkinter as tk
from tkinter import ttk
from ..core.config import BG,PANEL,PANEL2,LINE,TEXT,MUTED,ACCENT,SUCCESS,ERROR,WARNING,CODE_BG,HOVER,STAGES
from ..core import registry,state

def frame(parent,title,description):
    outer=tk.Frame(parent,bg=BG)
    top=tk.Frame(outer,bg=BG); top.pack(fill="x",pady=(0,14))
    tk.Label(top,text=title,bg=BG,fg=TEXT,font=("Segoe UI",18,"bold")).pack(anchor="w")
    tk.Label(top,text=description,bg=BG,fg=MUTED,font=("Segoe UI",9)).pack(anchor="w",pady=(3,0))
    return outer

def card(parent, title=None):
    f=tk.Frame(parent,bg=PANEL,highlightbackground=LINE,highlightthickness=1,bd=0)
    if title:
        tk.Label(f,text=title,bg=PANEL,fg=TEXT,font=("Segoe UI",11,"bold")).pack(anchor="w",padx=14,pady=(12,8))
    return f

def metric(parent,label,value,accent=TEXT):
    f=card(parent); tk.Label(f,text=label.upper(),bg=PANEL,fg=MUTED,font=("Segoe UI",8,"bold")).pack(anchor="w",padx=14,pady=(12,0)); tk.Label(f,text=str(value),bg=PANEL,fg=accent,font=("Segoe UI",23,"bold")).pack(anchor="w",padx=14,pady=(3,12)); return f

def button(parent,text,command,kind="normal"):
    bg={"primary":"#16536b","danger":"#281719"}.get(kind,"#13232e")
    fg=TEXT; border="#6e3c3c" if kind=="danger" else "#315267"
    return tk.Button(parent,text=text,command=command,bg=bg,fg=fg,activebackground=HOVER,activeforeground=TEXT,relief="flat",bd=0,padx=11,pady=7,cursor="hand2",font=("Segoe UI",9,"bold"),highlightbackground=border,highlightcolor=border,highlightthickness=1)

def toolbar(parent):
    return tk.Frame(parent,bg=BG)

def output(parent):
    wrap=tk.Frame(parent,bg=CODE_BG,highlightbackground=LINE,highlightthickness=1)
    t=tk.Text(wrap,bg=CODE_BG,fg="#b8c8d7",insertbackground=TEXT,relief="flat",font=("Consolas",9),wrap="word",padx=14,pady=12)
    t.pack(fill="both",expand=True)
    return wrap,t

def show(t,text): t.delete("1.0","end"); t.insert("end",text)
def selected_id(): return state.get("selected_dataset_id")
def table(parent,columns,rows):
    tv=ttk.Treeview(parent,columns=[c[0] for c in columns],show="headings",height=12)
    for key,label,width in columns: tv.heading(key,text=label); tv.column(key,width=width,anchor="w")
    for row in rows: tv.insert("","end",values=row)
    tv.pack(fill="both",expand=True,padx=12,pady=12)
    return tv
