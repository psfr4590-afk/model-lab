class Registry:
 def process(self):
  from .process_service import ProcessService; return ProcessService()
 def system(self):
  from .system_service import SystemService; return SystemService()
 def credentials(self):
  from .credential_service import CredentialService; return CredentialService()
 def crawler(self):
  from .crawler_service import CrawlerService; return CrawlerService()
 def dataset(self):
  from .dataset_service import DatasetService; return DatasetService()
 def pipeline(self):
  from .pipeline_service import PipelineService; return PipelineService()
 def training(self):
  from .training_service import TrainingService; return TrainingService()
 def output(self):
  from .output_service import OutputService; return OutputService()
 def logs(self):
  from .log_service import LogService; return LogService()
registry=Registry()
