from ..core import registry
from ..core.config import STAGES
class PipelineService:
 def run_stage(self,did,stage):
  if stage not in STAGES: raise ValueError(stage)
  return registry.process().post(f"/api/datasets/{did}/stage/{stage}")
 def stop(self,did): return registry.process().post(f"/api/datasets/{did}/stop")
 def state(self,did): return registry.process().get(f"/api/datasets/{did}")
