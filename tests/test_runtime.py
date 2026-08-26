import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from runtime import discover_project_root, is_project_root, write_environment_state

class RuntimeTests(unittest.TestCase):
    def test_canonical_root(self):
        self.assertTrue(is_project_root(ROOT))
        self.assertEqual(discover_project_root(ROOT), ROOT)

    def test_nested_root_discovery(self):
        with tempfile.TemporaryDirectory() as td:
            outer = Path(td) / "outer"
            inner = outer / "pretrain-pipeline" / "pretrain-pipeline"
            for name in ("run_pipeline.py", "bootstrap.py", "requirements.txt"):
                (inner / name).parent.mkdir(parents=True, exist_ok=True)
                (inner / name).write_text("", encoding="utf-8")
            (inner / "pipeline").mkdir()
            (inner / "config").mkdir()
            self.assertEqual(discover_project_root(outer), inner.resolve())

    def test_state_is_machine_readable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = write_environment_state(root, {
                "tools": {"cmake": {"status": "VERIFIED"}},
                "python_packages": {},
                "capabilities": {},
                "events": [{"component": "cmake", "to": "VERIFIED"}],
            })
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema"], 2)
            self.assertEqual(payload["tools"]["cmake"]["status"], "VERIFIED")
            self.assertIn("python", payload)
            self.assertIn("updated_at", payload)

if __name__ == "__main__":
    unittest.main()
