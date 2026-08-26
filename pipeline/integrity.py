"""Artifact integrity and atomic-write helpers."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def manifest_path(path: Path) -> Path:
    return path.with_name(path.name + ".manifest.json")


def write_manifest(path: Path, *, kind: str, rows: int | None = None, extra: dict | None = None) -> Path:
    payload = {
        "schema": 1,
        "kind": kind,
        "path": str(path),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if rows is not None:
        payload["rows"] = rows
    if extra:
        payload.update(extra)
    mp = manifest_path(path)
    tmp = mp.with_suffix(mp.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, mp)
    return mp


def artifact_valid(path: Path) -> bool:
    if not path.exists() or path.stat().st_size <= 0:
        return False
    mp = manifest_path(path)
    if not mp.exists():
        return False
    try:
        m = json.loads(mp.read_text(encoding="utf-8"))
        return (int(m.get("size", -1)) == path.stat().st_size
                and m.get("sha256") == sha256_file(path))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def atomic_jsonl_write(path: Path, producer) -> int:
    """Write producer() output atomically. Existing artifact remains intact on failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    count = 0
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            for item in producer():
                f.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
                count += 1
        if count == 0:
            raise RuntimeError(f"Refusing to commit empty artifact: {path}")
        os.replace(tmp_name, path)
        return count
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
