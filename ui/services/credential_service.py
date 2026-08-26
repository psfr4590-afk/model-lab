from ..core import registry
class CredentialService:
 def list(self): return registry.process().get("/api/credentials")
 def set(self,name,secret,provider="custom",kind="token",env_var="",description="",identity=""): return registry.process().post("/api/credentials",{"name":name,"secret":secret,"provider":provider,"kind":kind,"env_var":env_var,"description":description,"identity":identity})
 def delete(self,name): return registry.process().delete("/api/credentials/"+name)
 def test(self,name): return registry.process().post("/api/credentials/"+name+"/test")
