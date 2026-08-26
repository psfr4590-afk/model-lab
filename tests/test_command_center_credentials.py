import json

import pytest
from cryptography.fernet import Fernet

from command_center.secrets import CredentialStore


def make_store(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_CREDENTIAL_KEY", Fernet.generate_key().decode())
    return CredentialStore(tmp_path / "credentials.json")


def test_credential_store_encrypts_and_redacts(tmp_path, monkeypatch):
    store = make_store(tmp_path, monkeypatch)
    secret = "super-secret-token-123"

    result = store.set(
        "github",
        secret,
        provider="GitHub",
        kind="api-token",
        env_var="GITHUB_TOKEN",
        identity="test-user",
    )

    assert result["name"] == "github"
    assert "secret" not in result
    assert store.reveal("github") == secret
    assert store.environment() == {"GITHUB_TOKEN": secret}
    assert store.test("github")["ok"] is True

    raw = (tmp_path / "credentials.json").read_text(encoding="utf-8")
    assert secret not in raw
    assert "super-secret-token" not in json.dumps(store.list())


def test_credential_delete(tmp_path, monkeypatch):
    store = make_store(tmp_path, monkeypatch)
    store.set("x", "abc")
    assert store.delete("x") is True
    assert store.delete("x") is False
    with pytest.raises(KeyError):
        store.reveal("x")
