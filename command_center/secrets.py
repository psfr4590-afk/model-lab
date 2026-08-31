from __future__ import annotations

import base64
import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from .config import ROOT

LOCK = RLock()
STORE_PATH = ROOT / ".runtime" / "credentials.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _dpapi_protect(value: bytes) -> bytes:
    if platform.system() != "Windows":
        raise RuntimeError("Windows DPAPI is unavailable")
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(value)
    blob_in = DATA_BLOB(len(value), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    blob_out = DATA_BLOB()
    if not crypt32.CryptProtectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _dpapi_unprotect(value: bytes) -> bytes:
    if platform.system() != "Windows":
        raise RuntimeError("Windows DPAPI is unavailable")
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(value)
    blob_in = DATA_BLOB(len(value), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    blob_out = DATA_BLOB()
    if not crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _fallback_fernet():
    """Return a Fernet instance for non-Windows hosts.

    Raises a RuntimeError with actionable instructions if cryptography is
    missing or PIPELINE_CREDENTIAL_KEY is not set.
    """
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise RuntimeError(
            "Non-Windows credential storage requires the 'cryptography' package. "
            "Install it with: pip install cryptography"
        ) from exc
    key = os.environ.get("PIPELINE_CREDENTIAL_KEY", "")
    if not key:
        raise RuntimeError(
            "PIPELINE_CREDENTIAL_KEY is required on non-Windows hosts. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\" "
            "and set the environment variable PIPELINE_CREDENTIAL_KEY to that value."
        )
    try:
        return Fernet(key.encode())
    except Exception as exc:
        raise RuntimeError("PIPELINE_CREDENTIAL_KEY is invalid; ensure it is a valid Fernet key") from exc


def _encrypt(value: str) -> str:
    raw = value.encode("utf-8")
    if platform.system() == "Windows":
        out = _dpapi_protect(raw)
    else:
        out = _fallback_fernet().encrypt(raw)
    return base64.b64encode(out).decode("ascii")


def _decrypt(value: str) -> str:
    raw = base64.b64decode(value.encode("ascii"))
    if platform.system() == "Windows":
        out = _dpapi_unprotect(raw)
    else:
        out = _fallback_fernet().decrypt(raw)
    return out.decode("utf-8")


class CredentialStore:
    """Local credential store. Values are encrypted at rest and never exposed by list().

    Use CredentialStore.check_usable() at startup to get a (ok,message) tuple that
    can be surfaced to users instead of raising exceptions during app init.
    """

    def __init__(self, path: Path = STORE_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict:
        if not self.path.exists():
            return {"version": 1, "credentials": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("credential store is not an object")
            data.setdefault("version", 1)
            data.setdefault("credentials", {})
            return data
        except Exception as exc:
            raise RuntimeError(f"Unable to read credential store: {exc}") from exc

    def _save(self, data: dict) -> None:
        _atomic_write(self.path, data)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def list(self) -> list[dict]:
        with LOCK:
            data = self._load()
            out = []
            for name, item in sorted(data["credentials"].items()):
                env_var = item.get("env_var") or ""
                env_present = bool(env_var and os.environ.get(env_var))
                out.append({
                    "name": name,
                    "provider": item.get("provider", "custom"),
                    "type": item.get("type", "token"),
                    "env_var": env_var,
                    "description": item.get("description", ""),
                    "identity": item.get("identity", ""),
                    "updated_at": item.get("updated_at"),
                    "stored": True,
                    "environment_set": env_present,
                })
            return out

    def set(self, name: str, secret: str, provider: str = "custom", kind: str = "token", env_var: str = "", description: str = "", identity: str = "") -> dict:
        name = name.strip()
        if not name or not secret:
            raise ValueError("credential name and secret are required")
        with LOCK:
            data = self._load()
            old = data["credentials"].get(name, {})
            data["credentials"][name] = {
                "provider": provider.strip() or "custom",
                "type": kind.strip() or "token",
                "env_var": env_var.strip(),
                "description": description.strip(),
                "identity": identity.strip(),
                "secret": _encrypt(secret),
                "updated_at": _now(),
                "created_at": old.get("created_at", _now()),
            }
            self._save(data)
            return next(x for x in self.list() if x["name"] == name)

    def delete(self, name: str) -> bool:
        with LOCK:
            data = self._load()
            if name not in data["credentials"]:
                return False
            del data["credentials"][name]
            self._save(data)
            return True

    def reveal(self, name: str) -> str:
        with LOCK:
            data = self._load()
            item = data["credentials"].get(name)
            if not item:
                raise KeyError(name)
            return _decrypt(item["secret")

    def environment(self) -> dict[str, str]:
        """Return only explicitly mapped secrets for child pipeline processes."""
        env: dict[str, str] = {}
        with LOCK:
            data = self._load()
            for item in data["credentials"].values():
                var = str(item.get("env_var") or "").strip()
                if not var:
                    continue
                env[var] = _decrypt(item["secret"])
        return env

    def test(self, name: str) -> dict:
        secret = self.reveal(name)
        item = next(x for x in self.list() if x["name"] == name)
        return {"ok": bool(secret), "name": name, "provider": item["provider"], "env_var": item["env_var"], "length": len(secret)}


credentials = CredentialStore()
