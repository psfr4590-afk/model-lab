"""Lazy service registry."""
_services={}
def _get(name,cls):
    if name not in _services: _services[name]=cls()
    return _services[name]
def process():
    from ..services.process_service import ProcessService; return _get("process",ProcessService)
def system():
    from ..services.system_service import SystemService; return _get("system",SystemService)
def credentials():
    from ..services.credential_service import CredentialService; return _get("credentials",CredentialService)
def crawler():
    from ..services.crawler_service import CrawlerService; return _get("crawler",CrawlerService)
def dataset():
    from ..services.dataset_service import DatasetService; return _get("dataset",DatasetService)
def pipeline():
    from ..services.pipeline_service import PipelineService; return _get("pipeline",PipelineService)
def training():
    from ..services.training_service import TrainingService; return _get("training",TrainingService)
def output():
    from ..services.output_service import OutputService; return _get("output",OutputService)
def log():
    from ..services.log_service import LogService; return _get("log",LogService)
