"""Visual and runtime configuration for M²S Model Training Pipeline."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CC_BASE_URL = "http://127.0.0.1:8000"
WINDOW_TITLE = "M²S Model Training Pipeline"
WINDOW_SIZE = "1760x990"
WINDOW_MIN = (1280, 720)
BG = "#070b10"
PANEL = "#0e151d"
PANEL2 = "#121c26"
PANEL3 = "#091018"
LINE = "#243442"
TEXT = "#e7eef6"
MUTED = "#8295a8"
ACCENT = "#61d7ff"
SUCCESS = "#71e3a0"
ERROR = "#ff7070"
WARNING = "#ffd166"
CODE_BG = "#05080c"
HOVER = "#193746"
ACTIVE = "#12202b"
STAGES = ["crawl", "clean", "dedup", "weight", "tokenize", "shard", "train", "export"]
