"""
crawler.py — Crawler screen for Model Lab UI.

Displays:
  - Live per-source counters (fetched / skipped / errors) from the backend API
  - Domain signal panel (top domains by rolling avg score)
  - Crawl log tail
  - Control buttons: Start Crawl, Stop, Refresh
  - Per-source enable toggles displayed as status indicators
  - Trafilatura / bs4 fallback extraction stats when available
"""

from . import *
import tkinter as tk
from tkinter import messagebox


_SOURCE_ICONS = {
    "web":          "🌐",
    "github":       "🐙",
    "arxiv":        "📄",
    "huggingface":  "🤗",
    "google":       "🔍",
}

_STAT_KEYS = ["fetched", "skipped", "errors", "abandoned_domains"]
_STAT_LABELS = {
    "fetched":            "Fetched",
    "skipped":            "Skipped",
    "errors":             "Errors",
    "abandoned_domains":  "Abandoned",
}


class CrawlerScreen(tk.Frame):

    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.root = frame(
            self,
            "Crawler",
            "Monitor and control all five crawl sources — web, GitHub, ArXiv, HuggingFace, Google.",
        )
        self.root.pack(fill="both", expand=True)
        self._build()
        self.refresh()

    # ── Layout ─────────────────────────────────────────────────────────────

    def _build(self):
        # Toolbar
        bar = toolbar(self.root)
        bar.pack(fill="x", pady=(0, 10))
        button(bar, "↻  Refresh", self.refresh).pack(side="left")
        button(bar, "▶  Start Crawl", self.start, "primary").pack(side="left", padx=7)
        button(bar, "■  Stop", self.stop, "danger").pack(side="left")

        # Main two-column layout
        cols = tk.Frame(self.root, bg=BG)
        cols.pack(fill="both", expand=True)
        cols.columnconfigure(0, weight=3)
        cols.columnconfigure(1, weight=2)

        left  = tk.Frame(cols, bg=BG)
        right = tk.Frame(cols, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        right.grid(row=0, column=1, sticky="nsew")

        # ── Left: per-source stat cards ────────────────────────────────────
        src_card = card(left, "Source Counters")
        src_card.pack(fill="x", pady=(0, 10))
        self._src_rows: dict[str, dict[str, tk.Label]] = {}
        header = tk.Frame(src_card, bg=PANEL)
        header.pack(fill="x", padx=14, pady=(4, 2))
        for col, width, label in [
            ("src",       14, "Source"),
            ("fetched",   9,  "Fetched"),
            ("skipped",   9,  "Skipped"),
            ("errors",    9,  "Errors"),
            ("abandoned", 9,  "Abandoned"),
            ("status",    10, "Status"),
        ]:
            tk.Label(header, text=label, bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 8, "bold"), width=width, anchor="w").pack(side="left")

        for source in ["web", "github", "arxiv", "huggingface", "google"]:
            row = tk.Frame(src_card, bg=PANEL)
            row.pack(fill="x", padx=14, pady=2)
            icon = _SOURCE_ICONS.get(source, "")
            tk.Label(row, text=f"{icon} {source}", bg=PANEL, fg=TEXT,
                     font=("Consolas", 9), width=14, anchor="w").pack(side="left")
            labels: dict[str, tk.Label] = {}
            for key in ["fetched", "skipped", "errors", "abandoned"]:
                lbl = tk.Label(row, text="—", bg=PANEL, fg=MUTED,
                               font=("Consolas", 9), width=9, anchor="w")
                lbl.pack(side="left")
                labels[key] = lbl
            status_lbl = tk.Label(row, text="idle", bg=PANEL, fg=MUTED,
                                  font=("Segoe UI", 8), width=10, anchor="w")
            status_lbl.pack(side="left")
            labels["status"] = status_lbl
            self._src_rows[source] = labels
        tk.Frame(src_card, bg=PANEL, height=6).pack()

        # ── Left: extraction method stats ──────────────────────────────────
        ext_card = card(left, "Extraction Stats")
        ext_card.pack(fill="x", pady=(0, 10))
        self._ext_frame = ext_card
        self._ext_labels: dict[str, tk.Label] = {}
        for key, label in [
            ("trafilatura_used", "Trafilatura"),
            ("bs4_fallback",     "BS4 Fallback"),
            ("lang_rejected",    "Lang Rejected"),
            ("sitemaps_discovered", "Sitemap URLs"),
            ("issues_fetched",   "Issues (GH)"),
            ("citations_enriched","Citations (ArXiv)"),
        ]:
            row = tk.Frame(ext_card, bg=PANEL)
            row.pack(fill="x", padx=14, pady=2)
            tk.Label(row, text=label, bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 9), width=20, anchor="w").pack(side="left")
            lbl = tk.Label(row, text="—", bg=PANEL, fg=TEXT,
                           font=("Consolas", 9), anchor="w")
            lbl.pack(side="left")
            self._ext_labels[key] = lbl
        tk.Frame(ext_card, bg=PANEL, height=6).pack()

        # ── Left: crawl log tail ───────────────────────────────────────────
        log_card = card(left, "Crawl Log (tail)")
        log_card.pack(fill="both", expand=True)
        _, self._log_text = output(log_card)
        self._log_text.pack(fill="both", expand=True, padx=10, pady=10)

        # ── Right: domain signal panel ─────────────────────────────────────
        dom_card = card(right, "Domain Signal Scores")
        dom_card.pack(fill="x", pady=(0, 10))
        self._dom_frame = tk.Frame(dom_card, bg=PANEL)
        self._dom_frame.pack(fill="x", padx=14, pady=(4, 10))

        # ── Right: active processes ────────────────────────────────────────
        proc_card = card(right, "Active Crawler Processes")
        proc_card.pack(fill="both", expand=True)
        _, self._proc_text = output(proc_card)
        self._proc_text.pack(fill="both", expand=True, padx=10, pady=10)

    # ── Data refresh ────────────────────────────────────────────────────────

    def refresh(self):
        did = selected_id()

        # Update source counters from backend API
        try:
            svc   = registry.crawler()
            stats = svc.stats(did) if did else {}
        except Exception as e:
            stats = {}
            import sys; print(f"Crawler stats fetch failed: {e}", file=sys.stderr)

        for source, labels in self._src_rows.items():
            src_stats = stats.get(source, {})
            color_map = {
                "fetched":   SUCCESS if src_stats.get("fetched", 0) > 0 else MUTED,
                "skipped":   WARNING if src_stats.get("skipped", 0) > 0 else MUTED,
                "errors":    ERROR   if src_stats.get("errors", 0) > 0 else MUTED,
                "abandoned": WARNING if src_stats.get("abandoned_domains", 0) > 0 else MUTED,
            }
            labels["fetched"].config(
                text=str(src_stats.get("fetched", "—")),
                fg=color_map["fetched"])
            labels["skipped"].config(
                text=str(src_stats.get("skipped", "—")),
                fg=color_map["skipped"])
            labels["errors"].config(
                text=str(src_stats.get("errors", "—")),
                fg=color_map["errors"])
            labels["abandoned"].config(
                text=str(src_stats.get("abandoned_domains", "—")),
                fg=color_map["abandoned"])

            running = src_stats.get("running", False)
            labels["status"].config(
                text="● running" if running else "○ idle",
                fg=ACCENT if running else MUTED)

        # Extraction method stats (web-only)
        web_stats = stats.get("web", {})
        for key, lbl in self._ext_labels.items():
            val = web_stats.get(key) or stats.get("github", {}).get(key) or stats.get("arxiv", {}).get(key)
            if val is not None:
                lbl.config(text=str(val), fg=TEXT)
            else:
                lbl.config(text="—", fg=MUTED)

        # Domain signal
        for w in self._dom_frame.winfo_children():
            w.destroy()
        try:
            domains = registry.crawler().domain_signals(did) if did else []
        except Exception:
            domains = []
        if domains:
            for dom, score, count in domains[:12]:
                row = tk.Frame(self._dom_frame, bg=PANEL)
                row.pack(fill="x", pady=1)
                color = SUCCESS if score >= 0.6 else WARNING if score >= 0.35 else ERROR
                tk.Label(row, text=dom, bg=PANEL, fg=TEXT,
                         font=("Consolas", 8), width=28, anchor="w").pack(side="left")
                tk.Label(row, text=f"{score:.2f}", bg=PANEL, fg=color,
                         font=("Consolas", 8), width=6, anchor="e").pack(side="left")
                tk.Label(row, text=f"({count} pg)", bg=PANEL, fg=MUTED,
                         font=("Segoe UI", 7), width=8, anchor="w").pack(side="left")
        else:
            tk.Label(self._dom_frame, text="No domain signal data yet.",
                     bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=6)

        # Log tail
        try:
            log_lines = registry.crawler().log_tail(did, n=80) if did else []
            show(self._log_text, "\n".join(log_lines) if log_lines else "No log output yet.")
        except Exception as e:
            show(self._log_text, f"Log unavailable: {e}")

        # Process list
        try:
            proc_info = registry.crawler().processes()
            show(self._proc_text, proc_info or "No crawler processes detected.")
        except Exception as e:
            show(self._proc_text, f"Process inspection unavailable: {e}")

    # ── Actions ─────────────────────────────────────────────────────────────

    def start(self):
        did = selected_id()
        if not did:
            messagebox.showinfo("Crawler", "Select a dataset in Datasets first.")
            return
        try:
            registry.crawler().start(did)
            self.refresh()
        except Exception as e:
            messagebox.showerror("Crawler", str(e))

    def stop(self):
        did = selected_id()
        if not did:
            messagebox.showinfo("Crawler", "Select a dataset in Datasets first.")
            return
        try:
            registry.crawler().stop(did)
            self.refresh()
        except Exception as e:
            messagebox.showerror("Crawler", str(e))
