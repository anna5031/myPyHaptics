import asyncio
import threading
import time
from datetime import datetime

class Scheduler:
    def __init__(self, loop: asyncio.AbstractEventLoop = None):
        self._loop = loop or asyncio.get_event_loop()

    def schedule(self, at: datetime, callback):
        """Spawns a background thread to wait until the target_time."""
        t = threading.Thread(
            target=self._wait_and_dispatch, 
            args=(at.timestamp(), callback), 
            daemon=True
        )
        t.start()
        return t

    def _wait_and_dispatch(self, at: float, callback):
        """Runs in a background thread. Sleeps tightly and then delegates to the main loop."""
        remaining = at - time.time()
        
        # Coarse sleep to save CPU usage
        if remaining > 0.005:
            time.sleep(remaining - 0.005)
            
        # Fine-grained spin lock for extreme millisecond precision
        while time.time() < at:
            pass
            
        # Safely hop back over to the main asyncio thread
        self._loop.call_soon_threadsafe(self._dispatch, callback)

    def _dispatch(self, callback):
        """Runs strictly on the main asyncio event loop."""
        res = callback()
        
        # If the callback generated a coroutine, eagerly schedule it as a Task
        if asyncio.iscoroutine(res):
            self._loop.create_task(res)
