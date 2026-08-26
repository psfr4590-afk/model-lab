import tkinter as tk
from ..core.config import PANEL3, MUTED, TEXT, LINE, ACTIVE, HOVER, ACCENT
from ..core.navigation import NAV_ITEMS

ICONS = {"Dashboard":"▦","System":"⚙","Credentials":"⌁","Sources":"◈","Crawler":"◎","Dataset":"◫","Pipeline":"▶","Training":"△","CommandCenter":"≋","Outputs":"□","Diagnostics":"✓"}

class NavSidebar(tk.Frame):
    def __init__(self, parent, on_navigate):
        super().__init__(parent, bg=PANEL3, width=255, highlightthickness=0)
        self.pack_propagate(False)
        tk.Label(self, text="M²S MODEL TRAINING PIPELINE", bg=PANEL3, fg=TEXT,
                 font=("Segoe UI", 14, "bold"), anchor="w").pack(fill="x", padx=16, pady=(18, 0))
        tk.Label(self, text="LOCAL COMMAND CENTER", bg=PANEL3, fg=MUTED,
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x", padx=17, pady=(2, 18))
        self.buttons = {}
        for label, key in NAV_ITEMS:
            b = tk.Button(self, text=f"  {ICONS.get(key, '•')}   {label}",
                          command=lambda k=key: on_navigate(k),
                          bg=PANEL3, fg=MUTED, activebackground=HOVER, activeforeground=TEXT,
                          relief="flat", bd=0, anchor="w", padx=10, pady=9,
                          font=("Segoe UI", 10), cursor="hand2", highlightthickness=0)
            b.pack(fill="x", padx=9, pady=2)
            self.buttons[key] = b
        tk.Frame(self, bg=LINE, height=1).pack(fill="x", padx=15, pady=(14, 8))
        tk.Label(self, text="LOCALHOST ONLY\nExplicit actions required", bg=PANEL3, fg=MUTED,
                 font=("Consolas", 8), justify="left", anchor="w").pack(fill="x", padx=17)
        self.set_active("Dashboard")

    def set_active(self, key):
        for k, b in self.buttons.items():
            active = k == key
            b.configure(bg=ACTIVE if active else PANEL3,
                         fg=TEXT if active else MUTED,
                         font=("Segoe UI", 10, "bold" if active else "normal"))
