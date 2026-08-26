"""UI entry point. Starts the local Command Center when needed, then opens Tkinter."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui.core.application import Application, BackendManager


def main() -> int:
    backend = BackendManager(ROOT)
    backend.start()
    try:
        app = Application(backend=backend)
        app.mainloop()
    finally:
        backend.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
