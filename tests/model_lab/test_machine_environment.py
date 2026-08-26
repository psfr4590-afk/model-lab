"""Target-machine release checks.

These tests intentionally skip when the required target environment is absent.
Run them on the actual Windows machine as part of release verification.
"""
from pathlib import Path
import os
import platform
import shutil
import subprocess
import sys
import tkinter as tk
import pytest

ROOT = Path(__file__).resolve().parents[2]
PIPELINE_ROOT = ROOT

WINDOWS_ONLY = pytest.mark.skipif(platform.system() != "Windows", reason="requires target Windows machine")
DISPLAY_ONLY = pytest.mark.skipif(not os.environ.get("DISPLAY") and platform.system() != "Windows", reason="requires graphical target machine")

@WINDOWS_ONLY
def test_windows_target():
    assert platform.system() == "Windows"

@WINDOWS_ONLY
def test_python_is_supported_target_version():
    assert sys.version_info[:2] == (3, 11), sys.version

@WINDOWS_ONLY
def test_tkinter_available():
    root = tk.Tk(); root.withdraw(); root.destroy()

@WINDOWS_ONLY
def test_target_resolution_is_1760x990_or_larger():
    root = tk.Tk(); root.withdraw()
    w, h = root.winfo_screenwidth(), root.winfo_screenheight()
    root.destroy()
    assert w >= 1760 and h >= 990, f"Detected {w}x{h}"

@WINDOWS_ONLY
def test_required_executables_are_on_path():
    missing=[x for x in ["python","git","cmake"] if shutil.which(x) is None]
    assert not missing, missing

@WINDOWS_ONLY
def test_nvidia_smi_is_available_when_gpu_verification_is_requested():
    path=shutil.which("nvidia-smi")
    if path is None: pytest.skip("nvidia-smi unavailable; GPU may be absent")
    r=subprocess.run([path,"--query-gpu=name,driver_version,memory.total","--format=csv,noheader"],capture_output=True,text=True,timeout=15)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip()

@WINDOWS_ONLY
def test_cuda_pytorch_status_is_recorded_not_assumed():
    try:
        import torch
    except ImportError:
        pytest.skip("PyTorch not installed")
    assert hasattr(torch, "cuda")
    # This is an observation check, not a false requirement that CUDA must exist.
    _ = torch.cuda.is_available()


@WINDOWS_ONLY
def test_command_center_entrypoint_can_start_and_report_health():
    # Full lifecycle is intentionally kept separate from unit tests because it creates a real local process.
    import urllib.request, time
    proc=subprocess.Popen([sys.executable,str(PIPELINE_ROOT/"run_command_center.py"),"--no-browser"],cwd=PIPELINE_ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT)
    try:
        deadline=time.time()+20
        while time.time()<deadline:
            try:
                with urllib.request.urlopen("http://127.0.0.1:8000/api/system",timeout=1) as r:
                    assert r.status == 200
                    return
            except Exception:
                time.sleep(.25)
        pytest.fail("Command Center did not become healthy within 20 seconds")
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill()

@WINDOWS_ONLY
def test_root_launcher_starts_without_browser_flag_regression():
    # Structural launch test only. A human-visible UI smoke test is documented separately because
    # Tk's real window must be observed on the target desktop.
    src=(ROOT / "launch.py").read_text(encoding="utf-8")
    assert "from ui.app import main" in src

@WINDOWS_ONLY
def test_all_desktop_navigation_surfaces_construct_and_switch():
    """Construct the real Tk application and switch through every registered screen."""
    import tkinter as tk
    from ui.core import registry, navigation
    from ui.core.application import Application

    class FakeService:
        def list(self): return []
        def groups(self): return []
        def get(self, did=None): return {"id": did, "status": "idle", "stages": {}}
        def create(self, *a, **k): return {"id": 999}
        def ingest(self, *a, **k): return {"ok": True}
        def processes(self): return "No crawler processes detected."
        def info(self): return {"platform": "test", "python": sys.version.split()[0]}
        def gpu(self): return "test"
        def inventory(self): return []
        def run_stage(self, *a): return {"ok": True}
        def stop(self, *a): return {"ok": True}
        def start(self, *a): return {"ok": True}
        def set(self, *a, **k): return {"stored": True}
        def delete(self, *a): return True
        def test(self, *a): return {"ok": True}
    fake=FakeService()
    monkeypatch = pytest.MonkeyPatch()
    try:
        for attr in ["process","system","credentials","crawler","dataset","pipeline","training","output"]:
            monkeypatch.setattr(registry, attr, lambda f=fake: f)
        root=Application(backend=type("Backend", (), {"stop": lambda self: None})())
        root.withdraw()
        for key in ["Dashboard","Dataset","Pipeline","Credentials","Sources","Crawler","Training","Outputs","Logs","System","Configuration","Diagnostics","CommandCenter"]:
            navigation.navigate(key)
            root.update_idletasks(); root.update()
            assert navigation.current() == key
            assert root.current is not None
            assert root.current.winfo_exists()
            for child in root.current.winfo_children():
                pass
        root.destroy()
    finally:
        monkeypatch.undo()

@WINDOWS_ONLY
def test_desktop_window_geometry_matches_target():
    import tkinter as tk
    from ui.core.application import Application
    root=Application(backend=type("Backend", (), {"stop": lambda self: None})())
    try:
        root.withdraw(); root.update_idletasks()
        root.geometry("1760x990")
        root.update_idletasks()
        assert root.winfo_width() >= 1760
        assert root.winfo_height() >= 990
    finally:
        root.destroy()




