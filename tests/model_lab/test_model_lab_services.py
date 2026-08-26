"""Behavioral tests for service contracts using fakes, no live backend required."""
from pathlib import Path
import os
import sys
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui.services.pipeline_service import PipelineService
from ui.services.dataset_service import DatasetService
from ui.services.credential_service import CredentialService
from ui.services.training_service import TrainingService
from ui.services.crawler_service import CrawlerService

class FakeProcess:
    def __init__(self): self.calls=[]
    def get(self,path): self.calls.append(("GET",path,None)); return {"ok": True}
    def post(self,path,body=None): self.calls.append(("POST",path,body)); return {"ok": True}
    def delete(self,path): self.calls.append(("DELETE",path,None)); return {"ok": True}

@pytest.fixture
def fake_registry(monkeypatch):
    import ui.services.pipeline_service as ps
    import ui.services.dataset_service as ds
    import ui.services.credential_service as cs
    import ui.services.training_service as ts
    import ui.services.crawler_service as cr
    fake=FakeProcess()
    for mod in [ps,ds,cs,ts,cr]: monkeypatch.setattr(mod.registry, "process", lambda: fake)
    return fake

@pytest.mark.parametrize("stage", ["crawl","clean","dedup","weight","tokenize","shard","train","export"])
def test_pipeline_stage_posts_correct_route(fake_registry, stage):
    PipelineService().run_stage(7, stage)
    assert fake_registry.calls[-1] == ("POST", f"/api/datasets/7/stage/{stage}", None)

def test_pipeline_rejects_invalid_stage(fake_registry):
    with pytest.raises(ValueError): PipelineService().run_stage(7, "bogus")
    assert fake_registry.calls == []

def test_pipeline_stop(fake_registry):
    PipelineService().stop(7)
    assert fake_registry.calls[-1] == ("POST", "/api/datasets/7/stop", None)

def test_pipeline_state(fake_registry):
    PipelineService().state(7)
    assert fake_registry.calls[-1] == ("GET", "/api/datasets/7", None)

def test_dataset_list(fake_registry):
    DatasetService().list(); assert fake_registry.calls[-1] == ("GET", "/api/datasets", None)

def test_dataset_get(fake_registry):
    DatasetService().get(4); assert fake_registry.calls[-1] == ("GET", "/api/datasets/4", None)

def test_dataset_groups(fake_registry):
    DatasetService().groups(); assert fake_registry.calls[-1] == ("GET", "/api/groups", None)

def test_dataset_create(fake_registry):
    DatasetService().create("x","d","g")
    assert fake_registry.calls[-1] == ("POST", "/api/datasets", {"name":"x","description":"d","group_id":"g"})

def test_dataset_ingest(fake_registry):
    DatasetService().ingest(3,"C:/data")
    assert fake_registry.calls[-1] == ("POST", "/api/datasets/3/ingest", {"path":"C:/data"})

def test_credentials_list(fake_registry):
    CredentialService().list(); assert fake_registry.calls[-1] == ("GET", "/api/credentials", None)

def test_credentials_set(fake_registry):
    CredentialService().set("github","SECRET","GitHub","API token","GITHUB_TOKEN","d","id")
    assert fake_registry.calls[-1] == ("POST", "/api/credentials", {"name":"github","secret":"SECRET","provider":"GitHub","kind":"API token","env_var":"GITHUB_TOKEN","description":"d","identity":"id"})

def test_credentials_delete(fake_registry):
    CredentialService().delete("github"); assert fake_registry.calls[-1] == ("DELETE", "/api/credentials/github", None)

def test_credentials_test(fake_registry):
    CredentialService().test("github"); assert fake_registry.calls[-1] == ("POST", "/api/credentials/github/test", None)

def test_training_start(fake_registry):
    TrainingService().start(2); assert fake_registry.calls[-1] == ("POST", "/api/datasets/2/stage/train", None)

def test_training_stop(fake_registry):
    TrainingService().stop(2); assert fake_registry.calls[-1] == ("POST", "/api/datasets/2/stop", None)

def test_crawler_start(fake_registry):
    CrawlerService().start(2); assert fake_registry.calls[-1] == ("POST", "/api/datasets/2/stage/crawl", None)

def test_crawler_stop(fake_registry):
    CrawlerService().stop(2); assert fake_registry.calls[-1] == ("POST", "/api/datasets/2/stop", None)
