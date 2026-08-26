from ..core import registry
class DatasetService:
 def list(self): return registry.process().get("/api/datasets")
 def get(self,did): return registry.process().get(f"/api/datasets/{did}")
 def groups(self): return registry.process().get("/api/groups")
 def create(self,name,description="",group_id=None): return registry.process().post("/api/datasets",{"name":name,"description":description,"group_id":group_id})
 def ingest(self,did,path): return registry.process().post(f"/api/datasets/{did}/ingest",{"path":path})
