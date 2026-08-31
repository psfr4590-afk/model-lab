from . import frame, toolbar, metric, selected_id, registry
import tkinter as tk
from tkinter import messagebox
from ..core.config import BG, PANEL, MUTED, TEXT, SUCCESS

class TrainingScreen(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.root = frame(self, "Training", "Training status and controlled train/stop operations.")
        self.root.pack(fill="both", expand=True)
        bar = toolbar(self.root)
        bar.pack(fill="x")
        # metrics and box containers assumed to be created by frame(toolbar)
        self.metrics = getattr(self, "metrics", tk.Frame(self.root, bg=PANEL))
        self.box = getattr(self, "box", tk.Frame(self.root, bg=PANEL))

    def refresh(self):
        for w in self.metrics.winfo_children():
            w.destroy()
        for w in self.box.winfo_children():
            w.destroy()

        did = selected_id()
        if not did:
            tk.Label(self.box, text="No dataset selected.", bg=PANEL, fg=MUTED, font=("Segoe UI", 11)).pack(pady=40)
            return

        try:
            d = registry.training().state(did)
            d = d if isinstance(d, dict) else {}
        except Exception as e:
            d = {"error": str(e)}

        vals = [
            ("Status", d.get("status", "idle"), SUCCESS if d.get("status") == "running" else TEXT),
            ("Device", d.get("device", "—"), TEXT),
            ("Model", d.get("model", d.get("model_type", "85M target")), TEXT),
        ]

        for x in vals:
            metric(self.metrics, *x).pack(side="left", fill="x", expand=True, padx=(0, 10))

        tk.Label(
            self.box,
            text="Training remains an explicit pipeline stage. Opening this screen never starts training.",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 10),
        ).pack(anchor="w", padx=14, pady=16)

    def start(self):
        did = selected_id()
        if did and messagebox.askyesno("Training", "Start the train stage for the selected dataset?", parent=self):
            try:
                registry.training().start(did)
                self.refresh()
            except Exception as e:
                messagebox.showerror("Training", str(e))

    def stop(self):
        did = selected_id()
        if did:
            try:
                registry.training().stop(did)
                self.refresh()
            except Exception as e:
                messagebox.showerror("Training", str(e))
