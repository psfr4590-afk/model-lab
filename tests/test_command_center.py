from fastapi.testclient import TestClient

from command_center.web import app


def test_command_center_seeds_and_serves():
    with TestClient(app) as client:
        response = client.get('/api/datasets')
        assert response.status_code == 200
        datasets = response.json()
        assert len(datasets) >= 4
        assert [d['group_id'] for d in datasets[:4]] == [
            'swe_cs_systems',
            'ai_ml_cybersec_dataeng',
            'sci_reasoning_forensics_formal',
            'domain_finance_bio_robotics',
        ]
        page = client.get('/')
        assert page.status_code == 200
        assert 'M²S MODEL TRAINING PIPELINE' in page.text


def test_credential_store_roundtrip(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet
    from command_center.secrets import CredentialStore

    monkeypatch.setenv("PIPELINE_CREDENTIAL_KEY", Fernet.generate_key().decode())
    path = tmp_path / "credentials.json"
    store = CredentialStore(path)
    item = store.set("github", "super-secret", "GitHub", "API token", "GITHUB_TOKEN", "test", "krash")

    assert item["stored"] is True
    assert item["identity"] == "krash"
    assert store.reveal("github") == "super-secret"
    assert store.environment()["GITHUB_TOKEN"] == "super-secret"
    assert "super-secret" not in path.read_text(encoding="utf-8")


def test_credential_api_does_not_return_secret():
    from command_center.web import app
    from command_center.secrets import credentials
    from fastapi.testclient import TestClient

    original = credentials.path
    try:
        import tempfile
        credentials.path = __import__("pathlib").Path(tempfile.mkdtemp()) / "credentials.json"
        import os
        from cryptography.fernet import Fernet
        os.environ["PIPELINE_CREDENTIAL_KEY"] = Fernet.generate_key().decode()
        with TestClient(app) as client:
            r = client.post("/api/credentials", json={
                "name": "test", "secret": "do-not-return", "provider": "custom",
                "kind": "token", "env_var": "TEST_TOKEN", "identity": "user"
            })
            assert r.status_code == 200
            assert "secret" not in r.json()
            listing = client.get("/api/credentials")
            assert listing.status_code == 200
            body = listing.json()
            assert body[0]["name"] == "test"
            assert "do-not-return" not in listing.text
    finally:
        credentials.path = original
