from ..core import registry
class TrainingService:
 def start(self,did): return registry.process().post(f"/api/datasets/{did}/stage/train")
 def stop(self,did): return registry.process().post(f"/api/datasets/{did}/stop")
 def state(self,did): return registry.process().get(f"/api/datasets/{did}")
