"""cleaner.py — Pretraining data cleaner stage.

Pipeline: HTML strip → unicode normalize → length gate → exact-hash dedup
          → refusal/restriction filter → pass/drop/flag/redact
"""

from __future__ import annotations

import hashlib
import logging
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterator

import yaml

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

log = logging.getLogger("cleaner")


class Action(str, Enum):
    DROP   = "drop"
    FLAG   = "flag"
    REDACT = "redact"


@dataclass
class PatternGroup:
    name:     str
    enabled:  bool
    weight:   float
    patterns: list[re.Pattern]


@dataclass
class CleanerConfig:
    action:          Action
    score_threshold: float
    min_doc_length:  int
    max_doc_length:  int
    log_enabled:     bool
    log_level:       str
    log_file:        str
    log_matched_text: bool
    log_doc_preview: int
    html_enabled:    bool
    html_parser:     str
    unicode_enabled: bool
    unicode_form:    str
    strip_control_chars: bool
    dedup_enabled:   bool
    dedup_method:    str
    refusal_enabled: bool
    pattern_groups:  list[PatternGroup]
    instant_drop_enabled:  bool
    instant_drop_patterns: list[re.Pattern]


def _compile(raw: list[str]) -> list[re.Pattern]:
    out = []
    for p in raw:
        try:
            out.append(re.compile(p, re.IGNORECASE))
        except re.error as e:
            log.warning(f"Bad regex '{p}': {e}")
    return out


def load_config(path: str | Path) -> CleanerConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    g  = raw.get("general", {})
    lg = raw.get("logging", {})
    h  = raw.get("html", {})
    u  = raw.get("unicode", {})
    d  = raw.get("dedup", {})
    rf = raw.get("refusal_filter", {})

    groups = []
    for gname, gcfg in rf.get("pattern_groups", {}).items():
        groups.append(PatternGroup(
            name=gname, enabled=gcfg.get("enabled", True),
            weight=float(gcfg.get("weight", 1.0)),
            patterns=_compile(gcfg.get("patterns", [])),
        ))

    idp = rf.get("instant_drop_patterns", {})

    return CleanerConfig(
        action=Action(g.get("action", "drop")),
        score_threshold=float(g.get("score_threshold", 0.12)),
        min_doc_length=int(g.get("min_doc_length", 80)),
        max_doc_length=int(g.get("max_doc_length", 2_000_000)),
        log_enabled=lg.get("enabled", True),
        log_level=lg.get("level", "INFO"),
        log_file=lg.get("log_file", "output/logs/cleaner.log"),
        log_matched_text=lg.get("log_matched_text", True),
        log_doc_preview=int(lg.get("log_doc_preview", 120)),
        html_enabled=h.get("enabled", True),
        html_parser=h.get("parser", "lxml"),
        unicode_enabled=u.get("enabled", True),
        unicode_form=u.get("normalize_form", "NFKC"),
        strip_control_chars=u.get("strip_control_chars", True),
        dedup_enabled=d.get("enabled", True),
        dedup_method=d.get("method", "exact_hash"),
        refusal_enabled=rf.get("enabled", True),
        pattern_groups=groups,
        instant_drop_enabled=idp.get("enabled", True),
        instant_drop_patterns=_compile(idp.get("patterns", [])),
    )


@dataclass
class CleanResult:
    kept:   bool
    action: str
    text:   str
    score:  float = 0.0
    hits:   list[dict] = field(default_factory=list)
    doc_id: str = ""


class Cleaner:

    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path)
        self.cfg = load_config(self.config_path)
        self._seen: set[str] = set()
        self._mtime = self.config_path.stat().st_mtime
        self.stats = {
            "total": 0, "kept": 0,
            "dropped_refusal": 0, "dropped_short": 0,
            "dropped_long": 0, "dropped_dedup": 0,
            "flagged": 0, "redacted": 0,
        }
        log.info(f"Cleaner ready | action={self.cfg.action} threshold={self.cfg.score_threshold}")

    def reload(self):
        self.cfg   = load_config(self.config_path)
        self._mtime = self.config_path.stat().st_mtime
        log.info("Cleaner config reloaded")

    def _maybe_reload(self):
        try:
            mt = self.config_path.stat().st_mtime
            if mt != self._mtime:
                self.reload()
        except Exception:
            pass

    # ── Stage 1: HTML ────────────────────────────────────────────────────────

    def _strip_html(self, text: str) -> str:
        if not self.cfg.html_enabled:
            return text
        if BS4_AVAILABLE:
            soup = BeautifulSoup(text, self.cfg.html_parser)
            for tag in soup(["script", "style", "nav", "footer", "aside",
                              "header", "form", "noscript", "iframe"]):
                tag.decompose()
            return soup.get_text(separator=" ")
        return re.sub(r"<[^>]+>", " ", text)

    # ── Stage 2: Unicode ─────────────────────────────────────────────────────

    def _normalize(self, text: str) -> str:
        if not self.cfg.unicode_enabled:
            return text
        text = unicodedata.normalize(self.cfg.unicode_form, text)
        if self.cfg.strip_control_chars:
            text = "".join(
                c for c in text
                if unicodedata.category(c) not in ("Cc", "Cf") or c in ("\n", "\t")
            )
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    # ── Stage 3: Dedup ───────────────────────────────────────────────────────

    def _is_duplicate(self, text: str) -> bool:
        if not self.cfg.dedup_enabled:
            return False
        h = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
        if h in self._seen:
            return True
        self._seen.add(h)
        return False

    # ── Stage 4: Refusal filter ──────────────────────────────────────────────

    def _score(self, text: str) -> tuple[float, list[dict]]:
        hits, weighted = [], 0.0
        tokens = max(len(text.split()), 1)

        if self.cfg.instant_drop_enabled:
            for pat in self.cfg.instant_drop_patterns:
                m = pat.search(text)
                if m:
                    return 999.0, [{"group": "instant_drop", "pattern": pat.pattern,
                                    "span": m.span(),
                                    "matched": m.group(0) if self.cfg.log_matched_text else ""}]

        for grp in self.cfg.pattern_groups:
            if not grp.enabled:
                continue
            for pat in grp.patterns:
                for m in pat.finditer(text):
                    hits.append({"group": grp.name, "pattern": pat.pattern,
                                 "span": m.span(),
                                 "matched": m.group(0) if self.cfg.log_matched_text else ""})
                    weighted += grp.weight

        return weighted / tokens, hits

    def _redact(self, text: str, hits: list[dict]) -> str:
        chars = list(text)
        for h in sorted(hits, key=lambda x: x["span"][0], reverse=True):
            s, e = h["span"]
            chars[s:e] = list("[REMOVED]")
        return "".join(chars)

    # ── Public ───────────────────────────────────────────────────────────────

    def clean(self, text: str, doc_id: str = "") -> CleanResult:
        self._maybe_reload()
        self.stats["total"] += 1
        cfg = self.cfg

        text = self._strip_html(text)
        text = self._normalize(text)

        if len(text) < cfg.min_doc_length:
            self.stats["dropped_short"] += 1
            return CleanResult(kept=False, action="too_short", text="", doc_id=doc_id)

        if len(text) > cfg.max_doc_length:
            self.stats["dropped_long"] += 1
            return CleanResult(kept=False, action="too_long", text="", doc_id=doc_id)

        if self._is_duplicate(text):
            self.stats["dropped_dedup"] += 1
            log.info(f"[{doc_id}] DROP duplicate")
            return CleanResult(kept=False, action="duplicate", text="", doc_id=doc_id)

        score, hits = (0.0, [])
        if cfg.refusal_enabled:
            score, hits = self._score(text)

        preview = text[:cfg.log_doc_preview] if cfg.log_doc_preview else ""

        if score >= cfg.score_threshold:
            if cfg.action == Action.DROP:
                self.stats["dropped_refusal"] += 1
                log.info(f"[{doc_id}] DROP score={score:.4f} hits={len(hits)} preview={preview!r}")
                return CleanResult(kept=False, action="dropped", text="",
                                   score=score, hits=hits, doc_id=doc_id)
            elif cfg.action == Action.FLAG:
                self.stats["flagged"] += 1
                log.info(f"[{doc_id}] FLAG score={score:.4f}")
                return CleanResult(kept=True, action="flagged", text=text,
                                   score=score, hits=hits, doc_id=doc_id)
            elif cfg.action == Action.REDACT:
                self.stats["redacted"] += 1
                text = self._redact(text, hits)
                log.info(f"[{doc_id}] REDACT score={score:.4f} spans={len(hits)}")
                return CleanResult(kept=True, action="redacted", text=text,
                                   score=score, hits=hits, doc_id=doc_id)

        self.stats["kept"] += 1
        return CleanResult(kept=True, action="kept", text=text,
                           score=score, hits=hits, doc_id=doc_id)

    def print_stats(self):
        s = self.stats
        t = max(s["total"], 1)
        log.info(
            f"Cleaner stats | total={s['total']} kept={s['kept']} ({s['kept']/t*100:.1f}%) "
            f"drop_refusal={s['dropped_refusal']} drop_short={s['dropped_short']} "
            f"drop_long={s['dropped_long']} drop_dedup={s['dropped_dedup']} "
            f"flagged={s['flagged']} redacted={s['redacted']}"
        )

    def reset_dedup(self):
        self._seen.clear()