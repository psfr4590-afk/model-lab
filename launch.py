"""Canonical M²S Model Training Pipeline launcher."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from ui.app import main
raise SystemExit(main())
