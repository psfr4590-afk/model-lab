"""Thread-safe UI state."""
from threading import RLock
_lock=RLock(); _state={"api_reachable":False,"datasets":[],"selected_dataset_id":None,"selected_stage":"crawl","screen":"Dashboard"}
def get(key,default=None):
    with _lock:return _state.get(key,default)
def set(key,value):
    with _lock:_state[key]=value
def update(values):
    with _lock:_state.update(values)
def snapshot():
    with _lock:return dict(_state)
