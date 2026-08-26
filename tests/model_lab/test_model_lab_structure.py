"""Model Lab release-contract tests that do not require a GUI or live services."""
from pathlib import Path
import ast
import json
import re

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT

EXPECTED_NAV = [
    "Dashboard", "Datasets", "Pipeline", "Credentials", "Sources", "Crawler",
    "Training", "Outputs", "Logs", "System", "Configuration", "Diagnostics",
    "Command Center",
]
EXPECTED_STAGES = ["crawl", "clean", "dedup", "weight", "tokenize", "shard", "train", "export"]
EXPECTED_CREDS = {
    "github": ("GitHub", "GITHUB_TOKEN"),
    "huggingface": ("Hugging Face", "HF_TOKEN"),
    "google_api": ("Google", "GOOGLE_API_KEY"),
    "google_cx": ("Google", "GOOGLE_CX"),
}
SCREEN_FILES = {
    "Dashboard": "dashboard.py", "Datasets": "dataset.py", "Pipeline": "pipeline.py",
    "Credentials": "credentials.py", "Sources": "sources.py", "Crawler": "crawler.py",
    "Training": "training.py", "Outputs": "outputs.py", "Logs": "logs.py",
    "System": "system.py", "Configuration": "configuration.py", "Diagnostics": "diagnostics.py",
    "Command Center": "command_center.py",
}


def text(path):
    return path.read_text(encoding="utf-8")


def test_package_identity_is_model_lab():
    readme = text(ROOT / "README.md")
    assert "Model Lab" in readme
    assert "M²S Model Training Pipeline" in readme


def test_root_launcher_exists_and_uses_project_root():
    p = ROOT / "launch.py"
    assert p.exists()
    tree = ast.parse(text(p))
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "main" for n in ast.walk(tree))
    assert "resolve().parent" in text(p)


def test_navigation_contract_has_all_required_surfaces():
    src = text(ROOT / "ui/core/navigation.py")
    for item in EXPECTED_NAV:
        assert item in src


def test_all_navigation_screen_modules_exist():
    for name, filename in SCREEN_FILES.items():
        assert (ROOT / "ui/screens" / filename).exists(), name


def test_navigation_factories_cover_all_items():
    src = text(ROOT / "ui/core/application.py")
    for name, filename in SCREEN_FILES.items():
        stem = filename[:-3]
        assert stem in src, f"missing screen import: {name}"
    # Datasets is the human-facing navigation label; the registered factory key is Dataset.
    nav_src = text(ROOT / "ui/core/navigation.py")
    assert '("Datasets","Dataset")' in nav_src
    for key in ["Dashboard","System","Credentials","Sources","Crawler","Dataset","Pipeline","Training","CommandCenter","Outputs","Logs","Configuration","Diagnostics"]:
        assert f'"{key}":' in src


def test_pipeline_stage_contract_is_complete():
    src = text(ROOT / "ui/core/config.py")
    for stage in EXPECTED_STAGES:
        assert f'"{stage}"' in src


def test_pipeline_service_rejects_unknown_stage():
    src = text(ROOT / "ui/services/pipeline_service.py")
    assert "if stage not in STAGES: raise ValueError(stage)" in src


def test_all_stage_routes_are_exposed_by_command_center():
    src = text(PIPELINE / "command_center/web.py")
    assert "/api/datasets/{did}/stage/{name}" in src
    for stage in EXPECTED_STAGES:
        assert stage in text(PIPELINE / "command_center/service.py")


def test_stop_route_exists():
    assert "/api/datasets/{did}/stop" in text(PIPELINE / "command_center/web.py")


def test_dataset_routes_cover_list_create_get_ingest():
    src = text(PIPELINE / "command_center/web.py")
    for route in ["/api/datasets", "/api/datasets/{did}", "/api/datasets/{did}/ingest"]:
        assert route in src


def test_group_route_exists():
    assert "/api/groups" in text(PIPELINE / "command_center/web.py")


def test_system_route_exists():
    assert "/api/system" in text(PIPELINE / "command_center/web.py")


def test_credential_routes_cover_list_set_test_delete():
    src = text(PIPELINE / "command_center/web.py")
    for route in ["/api/credentials", "/api/credentials/{name}/test", "/api/credentials/{name}"]:
        assert route in src


def test_credential_presets_are_exactly_the_four_required_slots():
    src = text(ROOT / "ui/screens/credentials.py")
    for name, (provider, env) in EXPECTED_CREDS.items():
        assert f'"{name}"' in src
        assert f'"{provider}"' in src
        assert f'"{env}"' in src


def test_credentials_never_render_secret_value_in_list():
    src = text(PIPELINE / "command_center/secrets.py")
    assert '"secret":' in src
    assert '"secret": item' not in src
    assert 'return out' in src


def test_credential_store_supports_encryption_and_reveal():
    src = text(PIPELINE / "command_center/secrets.py")
    assert "_encrypt(secret)" in src
    assert "_decrypt(item[\"secret\"])" in src


def test_windows_uses_dpapi():
    src = text(PIPELINE / "command_center/secrets.py")
    assert "CryptProtectData" in src and "CryptUnprotectData" in src


def test_non_windows_fallback_requires_explicit_key():
    src = text(PIPELINE / "command_center/secrets.py")
    assert "PIPELINE_CREDENTIAL_KEY" in src
    assert "Fernet" in src


def test_backend_is_started_without_browser_by_desktop_launcher():
    src = text(ROOT / "ui/core/application.py")
    assert '"--no-browser"' in src
    assert "run_command_center.py" in src


def test_browser_is_not_opened_by_desktop_backend_manager():
    src = text(ROOT / "ui/core/application.py")
    assert "--no-browser" in src
    assert "webbrowser" not in src


def test_target_window_geometry_is_1760x990():
    src = text(ROOT / "ui/core/config.py")
    assert 'WINDOW_SIZE = "1760x990"' in src


def test_target_window_has_usable_minimum():
    src = text(ROOT / "ui/core/config.py")
    assert "WINDOW_MIN" in src
    assert "1280" in src and "720" in src


def test_visual_theme_is_defined_centrally():
    src = text(ROOT / "ui/core/config.py")
    for name in ["BG", "PANEL", "PANEL2", "LINE", "TEXT", "MUTED", "ACCENT", "SUCCESS", "ERROR"]:
        assert re.search(rf"^{name}\s*=", src, re.M)


def test_dataset_selection_navigates_to_pipeline():
    src = text(ROOT / "ui/screens/dataset.py")
    assert 'navigation.navigate("Pipeline")' in src
    assert "selected_dataset_id" in src


def test_dataset_creation_is_wired_to_service():
    src = text(ROOT / "ui/screens/dataset.py")
    assert "registry.dataset().create" in src


def test_dataset_ingest_is_wired_to_service():
    src = text(ROOT / "ui/screens/dataset.py")
    assert "registry.dataset().ingest" in src


def test_each_pipeline_stage_has_run_control():
    src = text(ROOT / "ui/screens/pipeline.py")
    assert "for i,s in enumerate(STAGES)" in src
    assert "self.run_stage(stage)" in src


def test_pipeline_stop_is_wired():
    src = text(ROOT / "ui/screens/pipeline.py")
    assert "registry.pipeline().stop(did)" in src


def test_credentials_save_is_wired():
    src = text(ROOT / "ui/screens/credentials.py")
    assert "registry.credentials().set" in src
    assert "Save / Replace" in src


def test_required_service_modules_exist():
    for service in ["process", "system", "credential", "crawler", "dataset", "pipeline", "training", "output", "log"]:
        assert (ROOT / "ui/services" / f"{service}_service.py").exists()


def test_documentation_contains_real_launch_commands():
    readme = text(ROOT / "README.md")
    assert "python .\\launch.py" in readme
    assert "run_pipeline.py --doctor" in readme


def test_documentation_mentions_machine_verification_boundary():
    readme = text(ROOT / "README.md")
    assert "Windows" in readme
    assert "1760x990" in readme or "1760×990" in readme


def test_no_common_secret_literals_are_committed():
    forbidden = ["g" + "hp_", "github" + "_pat_", "AI" + "za"]
    for p in ROOT.rglob("*"):
        if not p.is_file() or ".git" in p.parts or "llama.cpp" in p.parts:
            continue
        if p.name in {"README.md", ".env.example", "credentials.example.yaml"}:
            continue
        if p.suffix.lower() in {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".bin", ".pt"}:
            continue
        data = p.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            assert token not in data, f"possible secret literal {token} in {p}"


def test_pytest_scope_uses_training_bullshit_tests():
    src = text(ROOT / "pytest.ini")
    assert "testpaths = tests" in src


def test_release_docs_exist():
    for name in ["README.md", "START_HERE.md", "PROJECT_STATE.md", "VERIFICATION.md"]:
        assert (ROOT / name).exists()


def test_machine_verification_suite_is_present():
    assert (PIPELINE / "tests/model_lab/test_machine_environment.py").exists()
    assert (ROOT / "scripts" / "run_release_verification.ps1").exists()


def test_traceability_document_exists():
    assert (ROOT / "VERIFICATION_CHECKLIST.md").exists()


