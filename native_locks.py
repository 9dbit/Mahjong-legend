"""Single-process, per-business-key serialization without retaining idle locks."""
import threading
from weakref import WeakValueDictionary
_guard = threading.Lock()
_locks = WeakValueDictionary()

def operation_lock(key):
    with _guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _locks[key] = lock
        return lock

def active_lock_count():
    with _guard: return len(_locks)
