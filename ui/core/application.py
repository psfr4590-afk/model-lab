"""Main Tk application and local backend lifecycle."""
from __future__ import annotations
import subprocess, sys, time, urllib.request
import tkinter as tk
from pathlib import Path
from .config import *
from . import events, navigation, state

class BackendManager:
    def __init__(self, root: Path): self.root=root; self.proc=None
    def reachable(self):
        try:
            with urllib.request.urlopen(CC_BASE_URL + "/api/system", timeout=1): return True
        except Exception: return False
    def start(self):
        if self.reachable(): state.set("api_reachable", True); return
        script=self.root/"run_command_center.py"
        self.proc=subprocess.Popen([sys.executable,str(script),"--no-browser"],cwd=self.root,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT)
        deadline=time.time()+15
        while time.time()<deadline:
            if self.reachable(): state.set("api_reachable", True); return
            if self.proc.poll() is not None: break
            time.sleep(.25)
        state.set("api_reachable", False)
    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try: self.proc.wait(timeout=4)
            except subprocess.TimeoutExpired: self.proc.kill()

class Application(tk.Tk):
    def __init__(self, backend=None):
        super().__init__()
        self.backend=backend
        self.title("Model Lab · " + WINDOW_TITLE)
        self.geometry(WINDOW_SIZE)
        self.minsize(*WINDOW_MIN)
        self.configure(bg=BG)
        self._style(); self._build(); self._register_screens()
        events.subscribe(events.NAV_CHANGE, self._show)
        navigation.navigate("Dashboard")
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _style(self):
        pass

    def _build(self):
        header=tk.Frame(self,bg=PANEL,height=78); header.pack(fill="x"); header.pack_propagate(False)
        left=tk.Frame(header,bg=PANEL); left.pack(side="left",fill="y",padx=20)
        tk.Label(left,text="M²S CONTROL SURFACE",bg=PANEL,fg=MUTED,font=("Segoe UI",8,"bold")).pack(anchor="w",pady=(12,0))
        self.page_title=tk.Label(left,text=WINDOW_TITLE,bg=PANEL,fg=TEXT,font=("Segoe UI",18,"bold")); self.page_title.pack(anchor="w")
        right=tk.Frame(header,bg=PANEL); right.pack(side="right",fill="y",padx=18)
        self.api_badge=tk.Label(right,text=" ● API OFFLINE ",bg=PANEL2,fg=ERROR,font=("Consolas",9,"bold"),padx=8,pady=5); self.api_badge.pack(pady=21)
        body=tk.Frame(self,bg=BG); body.pack(fill="both",expand=True)
        from ..widgets.navigation import NavSidebar
        self.nav=NavSidebar(body,navigation.navigate); self.nav.pack(side="left",fill="y")
        self.content=tk.Frame(body,bg=BG); self.content.pack(side="left",fill="both",expand=True,padx=22,pady=20)
        self.current=None
        self.after(1000,self._refresh_badge)

    def _register_screens(self):
        from ..screens import dashboard,system,credentials,sources,crawler,dataset,pipeline,training,command_center,outputs,diagnostics,logs,configuration
        mapping={"Dashboard":dashboard.DashboardScreen,"System":system.SystemScreen,"Credentials":credentials.CredentialsScreen,"Sources":sources.SourcesScreen,"Crawler":crawler.CrawlerScreen,"Dataset":dataset.DatasetScreen,"Pipeline":pipeline.PipelineScreen,"Training":training.TrainingScreen,"CommandCenter":command_center.CommandCenterScreen,"Outputs":outputs.OutputsScreen,"Logs":logs.LogsScreen,"Configuration":configuration.ConfigurationScreen,"Diagnostics":diagnostics.DiagnosticsScreen}
        for k,v in mapping.items(): navigation.register(k,v)

    def _show(self,key):
        if self.current: self.current.destroy()
        self.nav.set_active(key)
        self.page_title.configure(text=key if key != "CommandCenter" else "Command Center")
        cls=navigation.factory(key)
        self.current=cls(self.content) if cls else tk.Frame(self.content,bg=BG)
        self.current.pack(fill="both",expand=True)

    def _refresh_badge(self):
        online=bool(state.get("api_reachable"))
        self.api_badge.configure(text=" ● API ONLINE " if online else " ● API OFFLINE ", fg=SUCCESS if online else ERROR)
        self.after(2000,self._refresh_badge)

    def _close(self):
        self.destroy()
