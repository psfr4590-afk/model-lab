#!/usr/bin/env python3
"""Runtime discovery, ownership, and environment-state utilities.

The pipeline must never depend on the caller's current working directory and
must never install Python packages into a different interpreter than the one
executing the pipeline.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

PROJECT_MARKERS = (
    "run_pipeline.py",
    "bootstrap.py",
    "requirements.txt",
    "pipeline",
    "config",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_project_root(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "run_pipeline.py").is_file()
        and (path / "bootstrap.py").is_file()
        and (path / "requirements.txt").is_file()
        and (path / "pipeline").is_dir()
        and (path / "config").is_dir()
    )


def discover_project_root(start: Path | None = None) -> Path:
    """Find the canonical project root without trusting cwd.

    Searches the starting location and its parents first, then bounded child
    directories. If multiple candidates exist at the same depth, fail loudly
    instead of choosing arbitrarily.
    """
    start = (start or Path(__file__).resolve().parent).resolve()

    candidates: list[Path] = []
    for p in (start, *start.parents):
        if is_project_root(p):
            return p

    # Handles archive layouts such as project/project. Keep this bounded so a
    # user's entire Desktop/drive is never recursively scanned by accident.
    queue: list[tuple[Path, int]] = [(start, 0)]
    seen: set[Path] = set()
    while queue:
        current, depth = queue.pop(0)
        if current in seen or depth > 3:
            continue
        seen.add(current)
        try:
            if is_project_root(current):
                candidates.append(current)
            for child in current.iterdir():
                if child.is_dir() and not child.name.startswith("."):
                    queue.append((child, depth + 1))
        except (OSError, PermissionError):
            continue

    unique = sorted({p.resolve() for p in candidates}, key=lambda p: (len(p.parts), str(p).lower()))
    if not unique:
        raise RuntimeError(
            f"Unable to locate pretrain pipeline root from {start}. "
            "Expected run_pipeline.py, bootstrap.py, requirements.txt, pipeline/, and config/."
        )
    if len(unique) > 1 and len({len(p.parts) for p in unique}) == 1:
        raise RuntimeError("Multiple possible pipeline roots found; refusing ambiguous execution:\n"
                           + "\n".join(f"  {p}" for p in unique))
    return unique[0]


def normalize_path(p: str | Path) -> str:
    return str(Path(p).resolve())


def executable_version(exe: Path) -> str | None:
    try:
        r = subprocess.run(
            [str(exe), "--version"],
            capture_output=True, text=True, timeout=10, check=False
        )
        text = (r.stdout or r.stderr).strip().splitlines()
        return text[0] if text else None
    except Exception:
        return None


def all_executables(names: Iterable[str]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for name in names:
        path = shutil.which(name)
        result[name] = {
            "status": "FOUND" if path else "MISSING",
            "path": normalize_path(path) if path else None,
            "version": executable_version(Path(path)) if path else None,
        }
    return result


def python_state() -> dict:
    prefix = Path(sys.prefix).resolve()
    base_prefix = Path(getattr(sys, "base_prefix", sys.prefix)).resolve()
    return {
        "status": "VERIFIED",
        "executable": normalize_path(sys.executable),
        "version": platform.python_version(),
        "prefix": str(prefix),
        "base_prefix": str(base_prefix),
        "virtualenv": prefix != base_prefix,
        "implementation": platform.python_implementation(),
    }


def write_environment_state(root: Path, state: dict) -> Path:
    runtime_dir = root / ".runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": 2,
        "updated_at": utc_now(),
        "project_root": str(root.resolve()),
        "python": python_state(),
        "environment": {
            "os": platform.platform(),
            "cwd_at_probe": str(Path.cwd().resolve()),
            "path": os.environ.get("PATH", ""),
        },
        "tools": state.get("tools", {}),
        "python_packages": state.get("python_packages", {}),
        "capabilities": state.get("capabilities", {}),
        "events": state.get("events", []),
    }
    path = runtime_dir / "environment.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path
