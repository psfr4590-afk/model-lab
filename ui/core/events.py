"""Tiny UI event bus."""
from __future__ import annotations
from collections import defaultdict
from typing import Any, Callable

_subscribers: dict[str,list[Callable[[Any],None]]] = defaultdict(list)
NAV_CHANGE="nav.change"
REFRESH="refresh"
STATUS="status"

def subscribe(event, callback): _subscribers[event].append(callback)
def unsubscribe(event, callback):
    try: _subscribers[event].remove(callback)
    except ValueError: pass
def publish(event, data=None):
    for cb in tuple(_subscribers[event]):
        try: cb(data)
        except Exception: pass
