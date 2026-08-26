"""Model Lab screen registry and navigation."""
from . import events,state
NAV_ITEMS=[("Dashboard","Dashboard"),("Datasets","Dataset"),("Pipeline","Pipeline"),("Credentials","Credentials"),("Sources","Sources"),("Crawler","Crawler"),("Training","Training"),("Outputs","Outputs"),("Logs","Logs"),("System","System"),("Configuration","Configuration"),("Diagnostics","Diagnostics"),("Command Center","CommandCenter")]
_registry={}
def register(key,factory): _registry[key]=factory
def navigate(key): state.set("screen",key); events.publish(events.NAV_CHANGE,key)
def current(): return state.get("screen","Dashboard")
def factory(key): return _registry.get(key)
