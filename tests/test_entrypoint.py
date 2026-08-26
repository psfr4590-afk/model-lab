import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class EntrypointTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "run_pipeline.py"), *args],
            cwd=ROOT, capture_output=True, text=True, check=False
        )

    def test_list_stages_needs_no_pipeline_dependencies(self):
        result = self.run_cli("--list-stages")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("crawl", result.stdout)
        self.assertIn("export", result.stdout)

if __name__ == "__main__":
    unittest.main()
